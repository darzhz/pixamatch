import cv2
import numpy as np
from PIL import Image, ImageOps
from .processor import FaceProcessor
from .database import DatabaseClient
from .storage import StorageClient
from .logger import debug_log, timeit

class SearchEngine:
    def __init__(self, processor: FaceProcessor, db: DatabaseClient, storage: StorageClient):
        debug_log("Initializing SearchEngine...")
        self.processor = processor
        self.db = db
        self.storage = storage
        self.threshold = 0.42

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
        # faces_orig = self.processor.detector.detect(img_resized_pil, threshold=0.5)
        faces_orig = self.processor.detector.detect(img_resized_pil)
        
        img_flipped = cv2.flip(img_resized, 1)
        # FIX: Convert flipped numpy BGR back to PIL RGB
        img_flipped_pil = Image.fromarray(cv2.cvtColor(img_flipped, cv2.COLOR_BGR2RGB))
        # faces_flipped = self.processor.detector.detect(img_flipped_pil, threshold=0.5)
        faces_flipped = self.processor.detector.detect(img_flipped_pil)
        
        best_img = img_resized
        best_faces = faces_orig
        
        if len(faces_flipped) > 0:
            # Note: Depending on your SCRFD version, best_faces[0] might be a dict or object
            # Ensure .probability is the correct attribute (sometimes it's .score)
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
            # Based on your DEBUG log:
            # face.bbox.upper_left.x, face.bbox.upper_left.y, etc.
            x1 = int(face.bbox.upper_left.x)
            y1 = int(face.bbox.upper_left.y)
            x2 = int(face.bbox.lower_right.x)
            y2 = int(face.bbox.lower_right.y)
        except AttributeError:
            # Fallback for different library versions
            debug_log("Standard Point access failed, trying dict access")
            x1 = int(face.bbox['upper_left']['x'])
            y1 = int(face.bbox['upper_left']['y'])
            x2 = int(face.bbox['lower_right']['x'])
            y2 = int(face.bbox['lower_right']['y'])

        # Boundary Safety
        h, w = best_img.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        face_crop = best_img[y1:y2, x1:x2]
        
        # Check if crop is valid (not empty)
        if face_crop.size == 0:
            debug_log("Empty face crop generated.")
            return None, "invalid_crop"

        ok, reason = self.processor.check_quality(face_crop)
        if not ok:
            debug_log(f"Selfie quality check failed: {reason}")
            return None, reason
            
        return face_crop, "ok"
    @timeit
    def search(self, basket_id, selfie_path):
        debug_log(f"Starting search in basket {basket_id} with selfie {selfie_path}")
        face_crop, status = self.normalize_selfie(selfie_path)
        if face_crop is None:
            return {"matches": [], "no_match": True, "reason": status}
        
        # Triple query vectors
        v_front = self.processor.get_embedding(face_crop)
        v_profile = self.processor.get_embedding(cv2.flip(face_crop, 1))
        
        lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl,a,b))
        face_low_light = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        v_low_light = self.processor.get_embedding(face_low_light)
        
        # Stage 1: Union Coarse Filter
        debug_log("Stage 1: Performing union coarse filter search...")
        results_front = self.db.search_faces("front", v_front, basket_id, top=50)
        results_profile = self.db.search_faces("profile", v_profile, basket_id, top=50)
        results_low = self.db.search_faces("low_light", v_low_light, basket_id, top=50)
        
        # Deduplicate by point ID and map to metadata
        candidates = {}
        for r in results_front + results_profile + results_low:
            candidates[r.id] = r
        debug_log(f"Stage 1 found {len(candidates)} unique candidates")
            
        # Stage 2: Weighted Score Fusion
        debug_log("Stage 2: Performing weighted score fusion...")
        final_results = []
        
        # To do true fusion, we need to get ALL vectors for these candidates
        pids = list(candidates.keys())
        if not pids:
            debug_log("No candidates found in Stage 1.")
            return {"matches": [], "no_match": True}
            
        full_candidates = self.db.client.retrieve(
            collection_name=self.db.collection_name,
            ids=pids,
            with_vectors=True,
            with_payload=True
        )
        
        weights = {"front": 0.5, "profile": 0.3, "low_light": 0.2}
        
        for cand in full_candidates:
            vectors = cand.vector
            # Defensive check: ensure vectors is a dictionary
            if not isinstance(vectors, dict):
                debug_log(f"Skipping candidate {cand.id}: vector data is not a dictionary.")
                continue

            # Compute cosine similarity manually for each vector
            def cos_sim(v1, v2):
                # Ensure both vectors exist and are not None
                if v1 is None or v2 is None: return 0
                return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
                
            # Use .get() to avoid KeyErrors if a specific named vector is missing
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
        
        # Deduplicate by image_path
        unique_images = {}
        for res in final_results:
            img_url = res["image_url"].split('?')[0] # base url
            if img_url not in unique_images or res["score"] > unique_images[img_url]["score"]:
                unique_images[img_url] = res
                
        sorted_results = sorted(unique_images.values(), key=lambda x: x["score"], reverse=True)
        debug_log(f"Search complete. Found {len(sorted_results)} matching images after deduplication.")
        
        return {
            "matches": sorted_results,
            "no_match": len(sorted_results) == 0
        }
