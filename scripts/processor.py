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
import io

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
        self.blur_threshold = float(os.getenv("BLUR_THRESHOLD", 40))

    def check_quality(self, face_crop, face_obj=None):
        h, w = face_crop.shape[:2]
        if h < 40 or w < 40:
            return False, "too_small"
        
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        if blur_score < self.blur_threshold:
            return False, f"too_blurry_{blur_score:.1f}"

        # Pose Gate
        if face_obj and hasattr(face_obj, 'kps'):
            kps = face_obj.kps
            lex, rex, nx = kps[0][0], kps[1][0], kps[2][0]
            if abs(rex - lex) > 0:
                ratio = (nx - lex) / (rex - lex)
                yaw_score = abs(ratio - 0.5) * 200
                if yaw_score > 70:
                    return False, f"extreme_pose_{yaw_score:.1f}"

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
        data = json.dumps({"done": done, "total": total, "faces_indexed": faces_indexed, "failed": failed})
        self.redis.set(f"progress:{basket_id}", data)
        self.redis.publish(f"events:{basket_id}", data)

    @timeit
    def process_basket_images(self, basket_id, image_paths):
        total = len(image_paths)
        done = 0; failed = 0; faces_indexed = 0
        batch_faces = []
        batch_size = 256
        
        for path in image_paths:
            try:
                img = cv2.imread(path)
                if img is None:
                    done += 1; failed += 1
                    self.update_progress(basket_id, done, total, faces_indexed, failed)
                    continue
                
                # Detection (on original resolution)
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
                faces = self.detector.detect(pil_img)
                
                # Compress for Storage
                filename = os.path.basename(path)
                comp_filename = os.path.splitext(filename)[0] + ".webp"
                s3_key = f"{basket_id}/{comp_filename}"
                
                # Save compressed to buffer
                comp_img = Image.fromarray(img_rgb)
                buffer = io.BytesIO()
                comp_img.save(buffer, format="WEBP", quality=85)
                buffer.seek(0)
                self.storage.upload_fileobj(buffer, s3_key)
                
                for face in faces:
                    x1, y1, x2, y2 = map(int, [face.bbox.upper_left.x, face.bbox.upper_left.y, face.bbox.lower_right.x, face.bbox.lower_right.y])
                    face_crop = img[max(0, y1):y2, max(0, x1):x2]
                    if face_crop.size == 0: continue
                    
                    ok, _ = self.check_quality(face_crop, face)
                    if not ok: continue
                    
                    v_front = self.get_embedding(face_crop)
                    kps = face.kps
                    lex, rex, nx = kps[0][0], kps[1][0], kps[2][0]
                    is_profile = abs(((nx - lex) / (rex - lex) if abs(rex-lex) > 0 else 0.5) - 0.5) > 0.25
                    
                    v_profile = v_front if is_profile else self.get_embedding(cv2.flip(face_crop, 1))
                    
                    lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
                    l, a, b = cv2.split(lab)
                    cl = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(l)
                    v_low_light = self.get_embedding(cv2.cvtColor(cv2.merge((cl,a,b)), cv2.COLOR_LAB2BGR))
                    
                    batch_faces.append({
                        "image_path": s3_key,
                        "vectors": {"front": v_front, "profile": v_profile, "low_light": v_low_light},
                        "bbox": [x1, y1, x2, y2],
                        "quality_score": float(face.probability)
                    })
                    faces_indexed += 1
                    if len(batch_faces) >= batch_size:
                        self.db.upsert_faces_batch(basket_id, batch_faces); batch_faces = []
                
                done += 1
                self.update_progress(basket_id, done, total, faces_indexed, failed)
            except Exception as e:
                debug_log(f"Err {path}: {e}"); done += 1; failed += 1
                self.update_progress(basket_id, done, total, faces_indexed, failed)

        if batch_faces: self.db.upsert_faces_batch(basket_id, batch_faces)
