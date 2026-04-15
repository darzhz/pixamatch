import cv2
import numpy as np
from PIL import Image, ImageOps
from .processor import FaceProcessor
from .database import DatabaseClient
from .storage import StorageClient
from .logger import debug_log, timeit
from qdrant_client.http import models
import os

class SearchEngine:
    def __init__(self, processor: FaceProcessor, db: DatabaseClient, storage: StorageClient):
        debug_log("Initializing SearchEngine...")
        self.processor = processor
        self.db = db
        self.storage = storage
        self.threshold = float(os.getenv("MATCH_THRESHOLD", 0.42))

    @timeit
    def normalize_selfie(self, image_path):
        debug_log(f"Normalizing selfie: {image_path}")
        # 1. EXIF correction
        img_pil = Image.open(image_path)
        img_pil = ImageOps.exif_transpose(img_pil)
        # Convert to BGR for OpenCV operations (resizing/flipping)
        img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        
        # 2. Mirror Detection
        h, w = img.shape[:2]
        scale = 640 / max(h, w)
        img_resized = cv2.resize(img, (int(w * scale), int(h * scale)))
        
        # FIX: Convert numpy BGR back to PIL RGB for the SCRFD detector
        img_resized_pil = Image.fromarray(cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB))
        faces_orig = self.processor.detector.detect(img_resized_pil)
        
        img_flipped = cv2.flip(img_resized, 1)
        img_flipped_pil = Image.fromarray(cv2.cvtColor(img_flipped, cv2.COLOR_BGR2RGB))
        faces_flipped = self.processor.detector.detect(img_flipped_pil)
        
        best_img = img_resized
        best_faces = faces_orig
        
        if len(faces_flipped) > 0:
            orig_prob = faces_orig[0].probability if len(faces_orig) > 0 else 0
            if faces_flipped[0].probability > orig_prob:
                debug_log("Flipped image has better detection. Using flipped.")
                best_img = img_flipped
                best_faces = faces_flipped
        
        if len(best_faces) == 0:
            debug_log(f"No face detected in selfie: {image_path}")
            return None, "no_face_detected"
        
        # 3. Crop and Quality Gate
        face = best_faces[0]
        
        try:
            x1 = int(face.bbox.upper_left.x)
            y1 = int(face.bbox.upper_left.y)
            x2 = int(face.bbox.lower_right.x)
            y2 = int(face.bbox.lower_right.y)
        except AttributeError:
            x1 = int(face.bbox['upper_left']['x'])
            y1 = int(face.bbox['upper_left']['y'])
            x2 = int(face.bbox['lower_right']['x'])
            y2 = int(face.bbox['lower_right']['y'])

        # Boundary Safety
        h, w = best_img.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        face_crop = best_img[y1:y2, x1:x2]
        
        if face_crop.size == 0:
            debug_log("Empty face crop generated.")
            return None, "invalid_crop"

        ok, reason = self.processor.check_quality(face_crop, face)
        if not ok:
            debug_log(f"Selfie quality check failed: {reason}")
            return None, reason
            
        return face_crop, "ok"

    @timeit
    def search(self, basket_id, selfie_paths):
        """
        selfie_paths can be a string (single path) or a dict with 'front', 'left', 'right'
        """
        debug_log(f"Starting search in basket {basket_id} with selfies {selfie_paths}")
        
        if isinstance(selfie_paths, str):
            selfie_paths = {"front": selfie_paths}
            
        crops = {}
        for pose, path in selfie_paths.items():
            crop, status = self.normalize_selfie(path)
            if crop is not None:
                crops[pose] = crop
            elif pose == "front":
                return {"matches": [], "no_match": True, "reason": f"Front face error: {status}"}

        # Triple query vectors
        # front vector
        v_front = self.processor.get_embedding(crops["front"])
        
        # profile vector: use real profile if available, else flip front
        if "left" in crops:
            v_profile = self.processor.get_embedding(crops["left"])
        elif "right" in crops:
            # If we only have right, we flip it to match the 'left' profile style usually indexed
            v_profile = self.processor.get_embedding(cv2.flip(crops["right"], 1))
        else:
            v_profile = self.processor.get_embedding(cv2.flip(crops["front"], 1))
            
        # low light vector: can use front or any other
        lab = cv2.cvtColor(crops["front"], cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl,a,b))
        face_low_light = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        v_low_light = self.processor.get_embedding(face_low_light)
        
        # Stage 1: Union Coarse Filter with hnsw_ef=64
        debug_log("Stage 1: Performing union coarse filter search (ef=64)...")
        search_params = models.SearchParams(hnsw_ef=64)
        
        results_front = self.db.client.query_points(
            collection_name=self.db.collection_name,
            query=v_front, using="front",
            query_filter=models.Filter(must=[models.FieldCondition(key="basket_id", match=models.MatchValue(value=basket_id))]),
            limit=50, search_params=search_params
        ).points
        
        results_profile = self.db.client.query_points(
            collection_name=self.db.collection_name,
            query=v_profile, using="profile",
            query_filter=models.Filter(must=[models.FieldCondition(key="basket_id", match=models.MatchValue(value=basket_id))]),
            limit=50, search_params=search_params
        ).points
        
        results_low = self.db.client.query_points(
            collection_name=self.db.collection_name,
            query=v_low_light, using="low_light",
            query_filter=models.Filter(must=[models.FieldCondition(key="basket_id", match=models.MatchValue(value=basket_id))]),
            limit=50, search_params=search_params
        ).points
        
        # Deduplicate
        candidates = {}
        for r in results_front + results_profile + results_low:
            candidates[r.id] = r
        debug_log(f"Stage 1 found {len(candidates)} unique candidates")
            
        # Stage 2: Weighted Score Fusion
        debug_log("Stage 2: Performing weighted score fusion...")
        pids = list(candidates.keys())
        if not pids:
            return {"matches": [], "no_match": True, "reason": "No initial candidates found in database."}
            
        full_candidates = self.db.client.retrieve(
            collection_name=self.db.collection_name,
            ids=pids, with_vectors=True, with_payload=True
        )
        
        # If we have real profiles, we might want to boost their importance
        # but for now we keep the weights consistent.
        weights = {"front": 0.5, "profile": 0.3, "low_light": 0.2}
        final_results = []
        
        def cos_sim(v1, v2):
            if v1 is None or v2 is None: return 0
            # Ensure v1 and v2 are numpy arrays for calculation
            v1_arr = np.array(v1)
            v2_arr = np.array(v2)
            norm = (np.linalg.norm(v1_arr) * np.linalg.norm(v2_arr))
            if norm == 0: return 0
            return np.dot(v1_arr, v2_arr) / norm
                
        for cand in full_candidates:
            vectors = cand.vector
            if not isinstance(vectors, dict): continue

            score = (
                weights["front"] * cos_sim(v_front, vectors.get("front")) +
                weights["profile"] * cos_sim(v_profile, vectors.get("profile")) +
                weights["low_light"] * cos_sim(v_low_light, vectors.get("low_light"))
            )
            
            if score > self.threshold:
                final_results.append({
                    "image_url": self.storage.get_signed_url(cand.payload["image_path"]),
                    "score": float(score),
                    "face_bbox": cand.payload["face_bbox"]
                })
        
        unique_images = {}
        for res in final_results:
            img_url = res["image_url"].split('?')[0]
            if img_url not in unique_images or res["score"] > unique_images[img_url]["score"]:
                unique_images[img_url] = res
                
        sorted_results = sorted(unique_images.values(), key=lambda x: x["score"], reverse=True)
        return {
            "matches": sorted_results,
            "no_match": len(sorted_results) == 0,
            "reason": "Threshold not met for any candidates." if len(sorted_results) == 0 else None
        }
