from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uuid
import json
import redis
import os
import shutil

from scripts.processor import FaceProcessor
from scripts.storage import StorageClient
from scripts.database import DatabaseClient
from scripts.search import SearchEngine
from scripts.logger import debug_log, timeit

app = FastAPI(title="Pixamatch API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared Clients
SCRFD_MODEL = "models/scrfd_2.5g_bnkps.onnx"
MFNET_MODEL = "models/mobilefacenet.onnx"

from scripts.metadata_db import MetadataDB

debug_log("Starting Pixamatch API...")
processor = FaceProcessor(SCRFD_MODEL, MFNET_MODEL)
db = DatabaseClient()
storage = StorageClient()
search_engine = SearchEngine(processor, db, storage)
r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), decode_responses=True)
meta_db = MetadataDB()

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

# Background Task
def run_ingestion(basket_id: str, paths: List[str]):
    debug_log(f"Starting background ingestion for basket {basket_id}...")
    processor.process_basket_images(basket_id, paths)
    
    # Final stats sync from Redis to SQLite
    data = r.get(f"progress:{basket_id}")
    if data:
        prog = json.loads(data)
        meta_db.update_stats(basket_id, prog["total"], prog["faces_indexed"])
    
    # Cleanup temp uploads
    for p in paths:
        if os.path.exists(p):
            os.remove(p)
    debug_log(f"Background ingestion finished for basket {basket_id}.")

# Endpoints
@app.post("/baskets", response_model=BasketResponse)
async def create_basket(basket: BasketCreate):
    debug_log(f"Creating basket: {basket.name}")
    basket_id = str(uuid.uuid4())
    # Save to Redis for progress tracking (transient)
    r.set(f"basket:{basket_id}:name", basket.name)
    # Save to SQLite for long-term persistence
    meta_db.create_basket(basket_id, basket.name)
    return {
        "basket_id": basket_id,
        "id": basket_id, # for frontend consistency
        "name": basket.name,
        "share_url": f"http://localhost:5173/find/{basket_id}"
    }

class BasketListResponse(BaseModel):
    baskets: List[dict]

@app.get("/baskets", response_model=BasketListResponse)
async def list_baskets():
    return {"baskets": meta_db.list_baskets()}

@app.post("/baskets/{basket_id}/images")
async def upload_images(basket_id: str, background_tasks: BackgroundTasks, images: List[UploadFile] = File(...)):
    debug_log(f"Uploading {len(images)} images to basket {basket_id}...")
    # Save to temp disk first
    temp_dir = f"uploads/{basket_id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    paths = []
    for img in images:
        path = f"{temp_dir}/{img.filename}"
        with open(path, "wb") as f:
            shutil.copyfileobj(img.file, f)
        paths.append(path)
    
    background_tasks.add_task(run_ingestion, basket_id, paths)
    return {"status": "Accepted", "count": len(images)}

@app.get("/baskets/{basket_id}/progress")
async def get_progress(basket_id: str):
    data = r.get(f"progress:{basket_id}")
    if not data:
        return {"done": 0, "total": 0, "faces_indexed": 0}
    return json.loads(data)

@app.get("/baskets/{basket_id}/info", response_model=BasketInfo)
async def get_basket_info(basket_id: str):
    info = meta_db.get_basket(basket_id)
    if not info:
        raise HTTPException(status_code=404, detail="Basket not found")
        
    progress = r.get(f"progress:{basket_id}")
    # If not in progress, use historical data from SQLite
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
async def search_faces(basket_id: str, selfie: UploadFile = File(...)):
    debug_log(f"Received search request for basket {basket_id}")
    # Save selfie to temp
    temp_path = f"uploads/selfie_{uuid.uuid4()}.jpg"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(selfie.file, f)
    
    try:
        results = search_engine.search(basket_id, temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    return results

@app.delete("/baskets/{basket_id}", status_code=204)
async def delete_basket(basket_id: str):
    debug_log(f"Deleting basket: {basket_id}")
    db.delete_basket(basket_id)
    meta_db.delete_basket(basket_id)
    r.delete(f"basket:{basket_id}:name")
    r.delete(f"progress:{basket_id}")
    return None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
