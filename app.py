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
from datetime import datetime
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

class CullLinkCreate(BaseModel):
    config: Optional[dict] = None

class CullDecision(BaseModel):
    image_path: str
    action: str # "keep" | "discard" | "unsure"

class CullDecisionsBatch(BaseModel):
    decisions: List[CullDecision]

class CullSubmit(BaseModel):
    token: str
    name: Optional[str] = None
    include_unsure: bool = False

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

# Culling Endpoints
@app.post("/baskets/{basket_id}/cull-links")
async def create_cull_link(basket_id: str, req: CullLinkCreate):
    token = str(uuid.uuid4())
    meta_db.create_cull_link(token, basket_id, req.config)
    return {"token": token, "url": f"http://localhost:5173/cull/{basket_id}/{token}"}

@app.get("/baskets/{basket_id}/cull/{token}")
async def get_cull_session(basket_id: str, token: str):
    link = meta_db.get_cull_link(token)
    if not link or link["basket_id"] != basket_id:
        raise HTTPException(status_code=404, detail="Invalid token or basket")
    
    # Check if session exists in Redis
    session_key = f"cull_session:{token}"
    session_data = r.get(session_key)
    
    if session_data:
        session = json.loads(session_data)
    else:
        # Create new session
        # Get all images for this basket (simplified: all images)
        keys, _ = storage.list_images(basket_id, limit=1000) # Limit for culling
        
        session = {
            "session_id": str(uuid.uuid4()),
            "basket_id": basket_id,
            "access_token": token,
            "status": "active",
            "queue": keys,
            "kept": [],
            "discarded": [],
            "unsure": []
        }
        r.set(session_key, json.dumps(session), ex=86400 * 7) # 1 week expiry
    
    # Return session with signed URLs for the queue
    queue_with_urls = [{"key": k, "url": storage.get_signed_url(k)} for k in session["queue"]]
    return {**session, "queue": queue_with_urls}

@app.patch("/baskets/{basket_id}/cull/{token}/decisions")
async def update_cull_decisions(basket_id: str, token: str, batch: CullDecisionsBatch):
    session_key = f"cull_session:{token}"
    session_data = r.get(session_key)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = json.loads(session_data)
    if session["status"] == "submitted":
        raise HTTPException(status_code=400, detail="Session already submitted")

    for dec in batch.decisions:
        # Remove from queue if present
        if dec.image_path in session["queue"]:
            session["queue"].remove(dec.image_path)
        
        # Add to correct list
        if dec.action == "keep":
            if dec.image_path not in session["kept"]: session["kept"].append(dec.image_path)
        elif dec.action == "discard":
            if dec.image_path not in session["discarded"]: session["discarded"].append(dec.image_path)
        elif dec.action == "unsure":
            # Re-queue at the end
            if dec.image_path not in session["queue"]: session["queue"].append(dec.image_path)
            if dec.image_path not in session["unsure"]: session["unsure"].append(dec.image_path)

    r.set(session_key, json.dumps(session), ex=86400 * 7)
    return {"status": "ok"}

@app.post("/baskets/{basket_id}/submit-cull")
async def submit_cull(basket_id: str, submit: CullSubmit):
    session_key = f"cull_session:{submit.token}"
    session_data = r.get(session_key)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = json.loads(session_data)
    if session["status"] == "submitted":
        raise HTTPException(status_code=400, detail="Session already submitted")
    
    # Mark as submitted
    session["status"] = "submitted"
    r.set(session_key, json.dumps(session), ex=86400 * 30) # Keep for a month
    
    # Create Studio Folder
    folder_id = str(uuid.uuid4())
    folder_name = submit.name or f"Culling Results ({datetime.now().strftime('%Y-%m-%d')})"
    
    kept_images = session["kept"]
    if submit.include_unsure:
        kept_images.extend(session["unsure"])
    
    meta_db.create_folder(folder_id, basket_id, folder_name, kept_images)
    
    return {"folder_id": folder_id, "status": "submitted"}

@app.get("/baskets/{basket_id}/folders")
async def list_folders(basket_id: str):
    folders = meta_db.list_folders(basket_id)
    # Add signed URLs for the first few images in each folder for preview
    for f in folders:
        f["previews"] = [storage.get_signed_url(k) for k in f["image_paths"][:4]]
    return {"folders": folders}

@app.patch("/folders/{folder_id}/read")
async def mark_folder_read(folder_id: str):
    meta_db.mark_folder_read(folder_id)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
