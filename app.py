from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import uuid
import json
import redis
import os
import shutil
import asyncio
from concurrent.futures import ProcessPoolExecutor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from scripts.processor import FaceProcessor
from scripts.storage import StorageClient
from scripts.database import DatabaseClient
from scripts.search import SearchEngine
from scripts.logger import debug_log, timeit
from scripts.metadata_db import MetadataDB

# Models
class BasketCreate(BaseModel):
    name: str

class BasketResponse(BaseModel):
    basket_id: str
    id: str
    name: str
    share_url: str

class BasketInfo(BaseModel):
    name: str
    image_count: int
    faces_indexed: int
    is_live: bool

class SearchResult(BaseModel):
    image_url: str
    score: float
    face_bbox: List[int]

class SearchResponse(BaseModel):
    matches: List[SearchResult]
    no_match: bool = False
    reason: Optional[str] = None

# Global Clients
SCRFD_MODEL = "models/scrfd_2.5g_bnkps.onnx"
MFNET_MODEL = "models/mobilefacenet.onnx"

app = FastAPI(title="Pixamatch API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), decode_responses=True)
meta_db = MetadataDB()

# Process Pool for CPU work
executor = None
worker_processor = None

def init_worker():
    global worker_processor
    # Fork-safe initialization inside worker
    worker_processor = FaceProcessor(SCRFD_MODEL, MFNET_MODEL)

@app.on_event("startup")
async def startup_event():
    global executor
    executor = ProcessPoolExecutor(max_workers=os.cpu_count(), initializer=init_worker)

@app.on_event("shutdown")
async def shutdown_event():
    if executor:
        executor.shutdown()

# Helper for Search (initialized in main process for search endpoint)
# Note: Search is fast enough for async if not heavily loaded, 
# or can also be offloaded if needed.
main_processor = FaceProcessor(SCRFD_MODEL, MFNET_MODEL)
db = DatabaseClient()
storage = StorageClient(
    endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
    bucket=os.getenv("MINIO_BUCKET", "pixamatch"),
    public_endpoint=os.getenv("MINIO_PUBLIC_ENDPOINT", None)
)
search_engine = SearchEngine(main_processor, db, storage)

def run_ingestion_sync(basket_id: str, paths: List[str]):
    debug_log(f"Worker starting ingestion for {basket_id}...")
    worker_processor.process_basket_images(basket_id, paths)
    
    # Final stats sync
    data = r.get(f"progress:{basket_id}")
    if data:
        prog = json.loads(data)
        meta_db.update_stats(basket_id, prog["total"], prog["faces_indexed"])
    
    for p in paths:
        if os.path.exists(p): os.remove(p)
    debug_log(f"Worker finished ingestion for {basket_id}.")

# Endpoints
@app.post("/baskets", response_model=BasketResponse)
async def create_basket(basket: BasketCreate):
    basket_id = str(uuid.uuid4())
    r.set(f"basket:{basket_id}:name", basket.name)
    meta_db.create_basket(basket_id, basket.name)
    return {
        "basket_id": basket_id, "id": basket_id, "name": basket.name,
        "share_url": f"http://localhost:5173/find/{basket_id}"
    }

@app.get("/baskets")
async def list_baskets():
    return {"baskets": meta_db.list_baskets()}

@app.post("/baskets/{basket_id}/images")
async def upload_images(basket_id: str, images: List[UploadFile] = File(...)):
    temp_dir = f"uploads/{basket_id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    paths = []
    for img in images:
        path = f"{temp_dir}/{img.filename}"
        with open(path, "wb") as f:
            shutil.copyfileobj(img.file, f)
        paths.append(path)
    
    # Offload to ProcessPool
    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, run_ingestion_sync, basket_id, paths)
    return {"status": "Accepted", "count": len(images)}

@app.get("/baskets/{basket_id}/progress")
async def get_progress(basket_id: str):
    data = r.get(f"progress:{basket_id}")
    return json.loads(data) if data else {"done": 0, "total": 0, "faces_indexed": 0}

@app.get("/baskets/{basket_id}/progress/events")
async def progress_events(basket_id: str):
    async def event_generator():
        pubsub = r.pubsub()
        pubsub.subscribe(f"events:{basket_id}")
        # Send initial state
        initial = r.get(f"progress:{basket_id}")
        if initial: yield f"data: {initial}\n\n"
        
        while True:
            # Check for messages more frequently for "instant" feel
            message = pubsub.get_message()
            if message and message['type'] == 'message':
                yield f"data: {message['data']}\n\n"
            await asyncio.sleep(0.1) 
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/baskets/{basket_id}/info", response_model=BasketInfo)
async def get_basket_info(basket_id: str):
    info = meta_db.get_basket(basket_id)
    if not info:
        raise HTTPException(status_code=404, detail="Basket not found")
        
    progress = r.get(f"progress:{basket_id}")
    prog_data = json.loads(progress) if progress else {
        "done": info["image_count"], 
        "total": info["image_count"], 
        "faces_indexed": info["faces_indexed"]
    }
    
    return {
        "name": info["name"],
        "image_count": prog_data["total"],
        "faces_indexed": prog_data["faces_indexed"],
        "is_live": info["is_live"]
    }

@app.post("/baskets/{basket_id}/search", response_model=SearchResponse)
async def search_faces(basket_id: str, front: UploadFile = File(...), left: Optional[UploadFile] = File(None), right: Optional[UploadFile] = File(None)):
    temp_paths = {}
    
    # Helper to save upload
    async def save_upload(upload: UploadFile, prefix: str):
        path = f"uploads/{prefix}_{uuid.uuid4()}.jpg"
        with open(path, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        return path

    try:
        temp_paths["front"] = await save_upload(front, "front")
        if left: temp_paths["left"] = await save_upload(left, "left")
        if right: temp_paths["right"] = await save_upload(right, "right")
        
        # Search with multiple poses
        results = search_engine.search(basket_id, temp_paths)
    finally:
        for p in temp_paths.values():
            if os.path.exists(p): os.remove(p)
            
    return results

@app.get("/baskets/{basket_id}/images")
async def get_basket_images(basket_id: str, limit: int = 50, marker: Optional[str] = None):
    keys, next_marker = storage.list_images(basket_id, limit, marker)
    images = [{"key": k, "url": storage.get_signed_url(k)} for k in keys]
    return {"images": images, "next_marker": next_marker}

@app.delete("/baskets/{basket_id}", status_code=204)
async def delete_basket(basket_id: str):
    db.delete_basket(basket_id)
    meta_db.delete_basket(basket_id)
    r.delete(f"basket:{basket_id}:name")
    r.delete(f"progress:{basket_id}")
    return None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
