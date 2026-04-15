import cv2
import numpy as np
import onnxruntime as ort
import os
from scrfd import SCRFD
from .storage import StorageClient
from .database import DatabaseClient
from .logger import debug_log, timeit
import redis
import json
from PIL import Image

class FaceProcessor:
    def __init__(self, scrfd_path: str, mfnet_path: str, redis_host=os.getenv("REDIS_HOST", "localhost")):
        debug_log(f"Initializing FaceProcessor with {scrfd_path} and {mfnet_path}...")
        self.detector = SCRFD.from_path(scrfd_path)
        
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        if "OpenVINOExecutionProvider" in ort.get_available_providers():
            providers = ["OpenVINOExecutionProvider"] + providers
            
        self.recognizer = ort.InferenceSession(mfnet_path, sess_options=opts, providers=providers)
        self.rec_size = (112, 112)
        
        self.storage = StorageClient()
        self.db = DatabaseClient()
        self.redis = redis.Redis(host=redis_host, decode_responses=True)

    def check_quality(self, face_crop):
        h, w = face_crop.shape[:2]
        if h < 40 or w < 40:
            return False, "too_small"
        
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        if blur_score < 80:
            return False, f"too_blurry_{blur_score:.1f}"
        
        return True, "ok"

    def get_embedding(self, face_crop):
        img = cv2.resize(face_crop, self.rec_size)
        img = img.astype(np.float32)
        img = (img - 127.5) / 128.0
        img = np.transpose(img, (2, 0, 1))
        img = np.expand_dims(img, axis=0)
        
        inputs = {self.recognizer.get_inputs()[0].name: img}
        net_out = self.recognizer.run(None, inputs)[0]
        return net_out[0].tolist()

    def update_progress(self, basket_id, done, total, faces_indexed, failed):
        self.redis.set(f"progress:{basket_id}", json.dumps({
            "done": done,
            "total": total,
            "faces_indexed": faces_indexed,
            "failed": failed
        }))

    @timeit
    def process_basket_images(self, basket_id, image_paths):
        total = len(image_paths)
        done = 0
        failed = 0
        faces_indexed = 0
        debug_log(f"Processing basket {basket_id} with {total} images...")
        
        for path in image_paths:
            try:
                debug_log(f"Processing image: {path}")
                img = cv2.imread(path)
                if img is None: 
                    debug_log(f"Failed to read image: {path}")
                    done += 1
                    failed += 1
                    self.update_progress(basket_id, done, total, faces_indexed, failed)
                    continue
                
                h, w = img.shape[:2]
                scale = 640 / max(h, w)
                img_resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                
                # Conversion to PIL for scrfd package compatibility
                img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
                
                # Detection
                faces = self.detector.detect(pil_img) # removed threshold=0.5 to use defaults if it causes issues
                debug_log(f"Detected {len(faces)} faces in {path}")
                
                # Storage original
                filename = os.path.basename(path)
                s3_key = f"{basket_id}/{filename}"
                self.storage.upload_image(path, s3_key)
                
                for i, face in enumerate(faces):
                    try:
                        # Extract coordinates from Bbox object
                        x1 = int(face.bbox.upper_left.x)
                        y1 = int(face.bbox.upper_left.y)
                        x2 = int(face.bbox.lower_right.x)
                        y2 = int(face.bbox.lower_right.y)
                        bbox = [x1, y1, x2, y2]
                        
                        face_crop = img_resized[max(0, y1):y2, max(0, x1):x2]
                        
                        if face_crop.size == 0: continue
                        
                        ok, reason = self.check_quality(face_crop)
                        if not ok: 
                            debug_log(f"Face {i} in {path} rejected: {reason}")
                            continue
                        
                        # Triple embeddings
                        v_front = self.get_embedding(face_crop)
                        v_profile = self.get_embedding(cv2.flip(face_crop, 1))
                        
                        lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
                        l, a, b = cv2.split(lab)
                        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
                        cl = clahe.apply(l)
                        limg = cv2.merge((cl,a,b))
                        face_low_light = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
                        v_low_light = self.get_embedding(face_low_light)
                        
                        self.db.upsert_face(
                            basket_id=basket_id,
                            image_path=s3_key,
                            vectors={
                                "front": v_front,
                                "profile": v_profile,
                                "low_light": v_low_light
                            },
                            bbox=bbox,
                            quality_score=float(face.probability)
                        )
                        faces_indexed += 1
                    except Exception as fe:
                        debug_log(f"Error processing face {i}: {fe}")
                
                done += 1
                debug_log(f"Indexed {faces_indexed} faces so far for {basket_id} ({done}/{total})")
                self.update_progress(basket_id, done, total, faces_indexed, failed)
                
            except Exception as e:
                debug_log(f"Error processing {path}: {e}")
                done += 1
                failed += 1
                self.update_progress(basket_id, done, total, faces_indexed, failed)
