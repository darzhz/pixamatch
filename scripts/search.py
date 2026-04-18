import cv2
import numpy as np
from PIL import Image, ImageOps
from .processor import FaceProcessor
from .database import DatabaseClient
from .storage import StorageClient
from .logger import debug_log, timeit
from qdrant_client.http import models
import os

import cv2
import numpy as np
from PIL import Image, ImageOps
from .processor import FaceProcessor, REFERENCE_POINTS
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
        self.threshold = float(os.getenv("MATCH_THRESHOLD", 0.30))

    def warp_face(self, img, kps):
        """Standardizes face to 112x112 using Affine Transformation"""
        M, _ = cv2.estimateAffinePartial2D(kps, REFERENCE_POINTS, method=cv2.RANSAC, ransacReprojThreshold=100)
        if M is None:
            return None
        return cv2.warpAffine(img, M, (112, 112), borderValue=0.0)

    @timeit
    def normalize_selfie(self, image_path):
        debug_log(f"Normalizing selfie: {image_path}")
        # 1. EXIF correction
        img_pil = Image.open(image_path)
        img_pil = ImageOps.exif_transpose(img_pil)
        # Convert to BGR for OpenCV operations
        img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        
        # 2. Scaling (to reasonable size for detection)
        h, w = img.shape[:2]
        scale = 1280 / max(h, w)
        img_resized = cv2.resize(img, (int(w * scale), int(h * scale)))
        
        # 3. Detection Strategy
        def detect_faces(cv_img):
            pil_img = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
            return self.processor.detector.detect(pil_img)

        # Attempt 1: Standard
        faces = detect_faces(img_resized)
        
        # Attempt 2: Rescue Mode (for compressed images)
        if not faces:
            debug_log("Standard detection failed. Attempting Rescue Mode (CLAHE + Blur)...")
            lab = cv2.cvtColor(img_resized, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(l)
            rescue_img = cv2.cvtColor(cv2.merge((l,a,b)), cv2.COLOR_LAB2BGR)
            rescue_img = cv2.GaussianBlur(rescue_img, (3,3), 0)
            faces = detect_faces(rescue_img)

        # Attempt 3: Mirror Fallback
        if not faces:
            debug_log("Attempting Mirror Fallback...")
            img_flipped = cv2.flip(img_resized, 1)
            faces = detect_faces(img_flipped)
            if faces:
                img_resized = img_flipped

        if not faces:
            debug_log(f"No face detected in selfie: {image_path}")
            return None, "no_face_detected"
        
        # 4. Alignment and Quality Gate
        face = faces[0]
        
        # Safe KPS access
        kps = self.processor.extract_kps(face)

        if kps is None:
            debug_log("No KPS found in selfie, fallback to simple crop.")
            try:
                x1, y1, x2, y2 = map(int, [face.bbox.upper_left.x, face.bbox.upper_left.y, face.bbox.lower_right.x, face.bbox.lower_right.y])
            except:
                x1, y1, x2, y2 = map(int, [face.bbox['upper_left']['x'], face.bbox['upper_left']['y'], face.bbox['lower_right']['x'], face.bbox['lower_right']['y']])
            face_aligned = cv2.resize(img_resized[max(0,y1):y2, max(0,x1):x2], (112, 112))
        else:
            face_aligned = self.warp_face(img_resized, kps)
            if face_aligned is None:
                return None, "alignment_failed"

        # Search-specific quality tolerance
        ok, reason = self.processor.check_quality(face_aligned, face)
        if not ok:
            debug_log(f"Selfie quality check failed: {reason}")
            if "too_blurry" in reason or "extreme_pose" in reason:
                debug_log("Search lenience: allowing borderline quality.")
                return face_aligned, "ok"
            return None, reason
            
        return face_aligned, "ok"

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
        has_real_profile = False
        if "left" in crops:
            v_profile = self.processor.get_embedding(crops["left"])
            has_real_profile = True
        elif "right" in crops:
            # If we only have right, we flip it to match the 'left' profile style usually indexed
            v_profile = self.processor.get_embedding(cv2.flip(crops["right"], 1))
            has_real_profile = True
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
        
        # Stage 1: Union Coarse Filter with hnsw_ef=48
        debug_log("Stage 1: Performing union coarse filter search (ef=48)...")
        search_params = models.SearchParams(hnsw_ef=48)
        
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
        
        # Dynamic Weighting Logic
        if has_real_profile:
            weights = {"front": 0.4, "profile": 0.4, "low_light": 0.2}
        else:
            # We only have a frontal selfie, don't rely too much on the "fake" profile vector
            weights = {"front": 0.7, "profile": 0.1, "low_light": 0.2}

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

