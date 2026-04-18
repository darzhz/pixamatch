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

# ArcFace Standard Reference Points for 112x112
REFERENCE_POINTS = np.array([
    [30.2946, 51.6963],  # Left Eye
    [65.5318, 51.5014],  # Right Eye
    [48.0252, 71.7366],  # Nose
    [33.5493, 92.3655],  # Left Mouth
    [62.7299, 92.2041]   # Right Mouth
], dtype=np.float32)

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

    @staticmethod
    def extract_kps(face):
        kps = None
        if hasattr(face, 'kps'): kps = face.kps
        elif isinstance(face, dict) and 'kps' in face: kps = face['kps']
        elif hasattr(face, 'landmarks'): kps = face.landmarks
        elif hasattr(face, 'keypoints'):
            kp = face.keypoints
            if hasattr(kp, 'left_eye'): # scrfd library object
                 kps = np.array([
                    [kp.left_eye.x, kp.left_eye.y],
                    [kp.right_eye.x, kp.right_eye.y],
                    [kp.nose.x, kp.nose.y],
                    [kp.left_mouth.x, kp.left_mouth.y],
                    [kp.right_mouth.x, kp.right_mouth.y]
                ], dtype=np.float32)
            else:
                kps = kp
        
        if kps is not None:
            return np.asarray(kps, dtype=np.float32)
        return None

    def warp_face(self, img, kps):
        """Standardizes face to 112x112 using Affine Transformation"""
        M, _ = cv2.estimateAffinePartial2D(kps, REFERENCE_POINTS, method=cv2.RANSAC, ransacReprojThreshold=100)
        if M is None:
            return None
        return cv2.warpAffine(img, M, self.rec_size, borderValue=0.0)

    def check_quality(self, face_crop, face_obj=None):
        h, w = face_crop.shape[:2]
        if h < 40 or w < 40:
            return False, "too_small"
        
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        if blur_score < self.blur_threshold:
            return False, f"too_blurry_{blur_score:.1f}"

        # Pose Gate
        if face_obj:
            # We check pose before alignment to avoid wasting CPU on extreme profiles
            kps = self.extract_kps(face_obj)

            if kps is not None:
                lex, rex, nx = kps[0][0], kps[1][0], kps[2][0]
                if abs(rex - lex) > 0:
                    ratio = (nx - lex) / (rex - lex)
                    yaw_score = abs(ratio - 0.5) * 200
                    if yaw_score > 70:
                        return False, f"extreme_pose_{yaw_score:.1f}"

        return True, "ok"

    def get_embedding(self, face_crop):
        # Image is already aligned and resized to 112x112 by warp_face
        img = face_crop.astype(np.float32)
        img = (img - 127.5) / 128.0
        img = np.transpose(img, (2, 0, 1))
        img = np.expand_dims(img, axis=0)
        
        inputs = {self.recognizer.get_inputs()[0].name: img}
        net_out = self.recognizer.run(None, inputs)[0]
        return net_out[0].tolist()

    def update_progress(self, basket_id, done, total, faces_indexed, failed, last_error=None):
        data = {
            "done": done, 
            "total": total, 
            "faces_indexed": faces_indexed, 
            "failed": failed
        }
        if last_error:
            data["last_error"] = last_error
            
        json_data = json.dumps(data)
        self.redis.set(f"progress:{basket_id}", json_data)
        self.redis.publish(f"events:{basket_id}", json_data)

    @timeit
    def process_basket_images(self, basket_id, image_paths):
        debug_log(f"Starting ingestion for basket {basket_id} with {len(image_paths)} images")
        total = len(image_paths)
        done = 0; failed = 0; faces_indexed = 0
        batch_faces = []
        batch_size = 256
        
        for path in image_paths:
            try:
                debug_log(f"Processing image: {path}")
                img = cv2.imread(path)
                if img is None:
                    err = f"Failed to load image: {os.path.basename(path)}"
                    debug_log(err)
                    done += 1; failed += 1
                    self.update_progress(basket_id, done, total, faces_indexed, failed, last_error=err)
                    continue
                
                # Detection (on original resolution)
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
                faces = self.detector.detect(pil_img)
                debug_log(f"Detected {len(faces)} faces in {os.path.basename(path)}")
                
                # Collect valid faces first
                valid_faces_in_image = []
                for face in faces:
                    # Quality check on simple crop first (cheap)
                    x1, y1, x2, y2 = map(int, [face.bbox.upper_left.x, face.bbox.upper_left.y, face.bbox.lower_right.x, face.bbox.lower_right.y])
                    quick_crop = img[max(0, y1):y2, max(0, x1):x2]
                    if quick_crop.size == 0: continue
                    
                    ok, reason = self.check_quality(quick_crop, face)
                    if not ok: 
                        debug_log(f"Face quality check failed in {os.path.basename(path)}: {reason}")
                        continue
                    
                    # Safe KPS access
                    kps = self.extract_kps(face)
                    
                    if kps is None:
                        debug_log(f"Warning: No KPS for face in {os.path.basename(path)}, skipping alignment")
                        face_aligned = cv2.resize(quick_crop, self.rec_size)
                        is_profile = False
                    else:
                        # Perform Facial Alignment
                        face_aligned = self.warp_face(img, kps)
                        if face_aligned is None:
                            debug_log(f"Alignment failed for face in {os.path.basename(path)}")
                            continue
                            
                        lex, rex, nx = kps[0][0], kps[1][0], kps[2][0]
                        is_profile = abs(((nx - lex) / (rex - lex) if abs(rex-lex) > 0 else 0.5) - 0.5) > 0.25
                    
                    v_front = self.get_embedding(face_aligned)
                    v_profile = v_front if is_profile else self.get_embedding(cv2.flip(face_aligned, 1))
                    
                    lab = cv2.cvtColor(face_aligned, cv2.COLOR_BGR2LAB)
                    l, a, b = cv2.split(lab)
                    cl = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(l)
                    v_low_light = self.get_embedding(cv2.cvtColor(cv2.merge((cl,a,b)), cv2.COLOR_LAB2BGR))
                    
                    valid_faces_in_image.append({
                        "vectors": {"front": v_front, "profile": v_profile, "low_light": v_low_light},
                        "bbox": [x1, y1, x2, y2],
                        "quality_score": float(face.probability)
                    })

                # Only upload if we have indexed faces
                if valid_faces_in_image:
                    filename = os.path.basename(path)
                    comp_filename = os.path.splitext(filename)[0] + ".webp"
                    s3_key = f"{basket_id}/{comp_filename}"
                    
                    # Upload compressed version
                    comp_img = Image.fromarray(img_rgb)
                    buffer = io.BytesIO()
                    comp_img.save(buffer, format="WEBP", quality=85)
                    buffer.seek(0)
                    self.storage.upload_fileobj(buffer, s3_key)
                    
                    for vf in valid_faces_in_image:
                        vf["image_path"] = s3_key
                        batch_faces.append(vf)
                        faces_indexed += 1
                        
                    debug_log(f"Indexed {len(valid_faces_in_image)} faces and uploaded {s3_key}")
                else:
                    debug_log(f"Skipping storage for {os.path.basename(path)} (no valid faces found)")

                if len(batch_faces) >= batch_size:
                    self.db.upsert_faces_batch(basket_id, batch_faces); batch_faces = []
                
                done += 1
                self.update_progress(basket_id, done, total, faces_indexed, failed)
            except Exception as e:
                err = f"Error processing {os.path.basename(path)}: {str(e)}"
                debug_log(err)
                done += 1; failed += 1
                self.update_progress(basket_id, done, total, faces_indexed, failed, last_error=err)

        if batch_faces: 
            debug_log(f"Upserting final batch of {len(batch_faces)} faces")
            self.db.upsert_faces_batch(basket_id, batch_faces)
        
        debug_log(f"Ingestion finished for {basket_id}. Total: {total}, Done: {done}, Failed: {failed}, Faces: {faces_indexed}")
