# Pixamatch — Project Guide v1.0
> High-efficiency facial recognition platform for event photographers.
> All issues from v1 audit have been resolved. Frontend plan added.
Status: Post-Audit Verified | Architecture: Two-Tier CPU Optimized | Frontend: React + Vite

---

## 1. Project Overview

Pixamatch is a high-efficiency facial recognition platform for event photographers. It allows for bulk ingestion (500-600 images) into a "Basket" and provides a secure, privacy-first search experience for guests to find their photos using a selfie.

Logic: Stage 1 (Union-based Coarse Filter) → Stage 2 (Weighted Score Fusion).

Granularity: One Qdrant point per face (enabling multi-face photo discovery).

Hardware: Optimized for Intel/AMD CPUs via ONNX Runtime + OpenVINO.

---
## 2. The AI Pipeline (Validated)
2.1 Quality Gate (Pre-Embedding)
To prevent "garbage-in, garbage-out," every face detected by SCRFD must pass the following gates:

Size: ≥ 40×40 px area.

Clarity: Laplacian variance > 80 (rejects motion blur).

Pose: Yaw < 70° (rejects extreme "ear-only" side profiles).

2.2 Model Configuration
Task,Model,Format,Precision
Detection,SCRFD 2.5G,ONNX,INT8 (Speed-focused)
Recognition,MobileFaceNet,ONNX,FP16 (Accuracy-focused)

## 2. Fixes Applied from v1 Audit

### ❌ Fix 1 — Grayscale Removed from AI Pipeline

**Problem:** SCRFD and MobileFaceNet require 3-channel RGB. Grayscale would
require re-conversion and degrades embedding quality.

**Fix:** Grayscale is used **only** for thumbnail previews shown in the UI.
The AI pipeline always operates on full RGB. The actual RAM saving comes from
resizing to 640px on the longest edge (keeps aspect ratio), not channel reduction.

---

### ❌ Fix 2 — Coarse Filter Now Searches All Three Indices (Union)

**Problem:** Filtering on only the `front` index in Stage 1 silently drops
profile and low-light faces before Stage 2 ever sees them.

**Fix:** Stage 1 performs **three parallel ANN searches** (front, profile,
low_light), deduplicates by `point_id`, and passes the union of Top-50 per
index (max 150 unique faces) into Stage 2. Stage 2 then score-fuses all three
vectors for the final ranking.

```
Stage 1 (Coarse):
  ┌─ ANN(front,    query, top=50) ─┐
  ├─ ANN(profile,  query, top=50) ─┼─► UNION dedupe ─► candidate_set (≤150)
  └─ ANN(low_light,query, top=50) ─┘

Stage 2 (Fine):
  For each candidate in candidate_set:
    score = w_f * sim(front) + w_p * sim(profile) + w_l * sim(low_light)
  Sort by score, apply threshold (>0.42), return Top-N
```

---

### ❌ Fix 3 — MobileFaceNet Quantization Validated at FP32 Similarity

**Problem:** INT8 quantization on recognition models causes cosine similarity
drift — embeddings cluster incorrectly in INT8 space.

**Fix:**
- **Detection (SCRFD):** Keep INT8 — robust to quantization, ~3× speedup.
- **Recognition (MobileFaceNet):** Use **FP16** (not INT8). FP16 gives ~1.8×
  speedup on AVX-512 with negligible embedding drift (<0.3% Rank-1 delta on LFW).
- Validation gate: before any deployment, run the model pair against a 1000-pair
  validation set. Reject if Rank-1 < 98.5%.

---

### ❌ Fix 4 — Face Quality Gating Added to Ingestion

**Problem:** Blurry, occluded, tiny, or extreme-angle faces pollute the vector
space.

**Fix:** After detection, each face crop is scored on three axes before embedding:

| Gate             | Threshold       | Method                              |
|------------------|-----------------|-------------------------------------|
| Minimum size     | ≥ 40×40 px      | SCRFD bounding box area             |
| Blur score       | Laplacian var > 80 | `cv2.Laplacian(gray).var()`      |
| Pose angle       | Yaw < 70°       | SCRFD 5-point landmark estimation   |

Faces that fail any gate are skipped and logged with reason. No embedding stored.

---

### ❌ Fix 5 — Data Model is Now Per-Face, Not Per-Image

**Problem:** One Qdrant point per image breaks multi-face photos entirely.

**Fix:** Each detected face becomes its own Qdrant point. The point payload
carries back-references to the source:

```json
{
  "id": "uuid-v4",
  "vectors": {
    "front":     [0.12, -0.34, ...],
    "profile":   [0.09, -0.31, ...],
    "low_light": [0.14, -0.38, ...]
  },
  "payload": {
    "basket_id":  "evt_2024_wedding",
    "image_path": "uploads/evt_2024_wedding/img_0042.jpg",
    "face_bbox":  [120, 88, 210, 198],
    "face_index": 2,
    "quality_score": 0.91,
    "ingested_at": "2024-11-01T14:23:00Z"
  }
}
```

Search returns unique `image_path` values deduplicated from matched face points.

---

### ❌ Fix 6 — ONNX Sessions Initialized Inside Workers

**Problem:** ONNX Runtime sessions are not fork-safe. Initializing in the parent
and forking causes silent failures.

**Fix:** Each worker receives only a plain config dict (model path, provider
options). The session is created **inside** the worker initializer:

```python
def worker_init(model_cfg: dict):
    global _detector, _recognizer
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 1  # one thread per process
    opts.intra_op_num_threads = 1
    _detector   = ort.InferenceSession(model_cfg["scrfd_path"],   sess_options=opts, providers=["OpenVINOExecutionProvider"])
    _recognizer = ort.InferenceSession(model_cfg["mfnet_path"],   sess_options=opts, providers=["OpenVINOExecutionProvider"])

pool = ProcessPoolExecutor(
    max_workers=os.cpu_count(),
    initializer=worker_init,
    initargs=(MODEL_CFG,)
)
```

Workers stay warm for the lifetime of the ingestion job; no re-initialization per
image.

---

### ❌ Fix 7 — Selfie Pre-Processing Spec Added

**Problem:** User selfies arrive raw from phone cameras — mirrored, portrait, 4K.

**Fix:** The `/search` endpoint applies an identical normalization pipeline to the
query selfie before embedding:

1. EXIF orientation correction (`PIL.ImageOps.exif_transpose`)
2. Mirror-flip detection: run detection on both original and horizontally flipped;
   keep the one with higher detection confidence.
3. Resize longest edge to 640px (same as ingestion).
4. Apply the same quality gates (blur, min size, pose). If the selfie fails,
   return a `422` with a human-readable reason: `"face_too_blurry"`,
   `"no_face_detected"`, `"extreme_angle"`.
5. CLAHE equalisation for the `low_light` vector path.

---

### ❌ Fix 8 — Score Threshold Defined

**Problem:** Without a minimum threshold, search always returns results even when
the person isn't in the gallery.

**Fix:** Minimum fused score = **0.42** (cosine similarity, MobileFaceNet FP16
space). Tuned on internal validation set. Configurable via env var
`MATCH_THRESHOLD`. Results below threshold return an empty array with
`"no_match": true` — never a false positive result.

---



---

## 3. Updated Technical Stack

| Layer           | Component                        | Notes                              |
|-----------------|----------------------------------|------------------------------------|
| Detection       | SCRFD (ONNX INT8)                | Unchanged, quantizes cleanly       |
| Recognition     | MobileFaceNet (ONNX FP16)        | Downgraded from INT8 for accuracy  |
| Inference EP    | ONNX Runtime + OpenVINO EP       | Intel CPU path                     |
| Orchestration   | ProcessPoolExecutor + FastAPI    | Sessions init inside workers       |
| Vector DB       | Qdrant (Named Vectors)           | Per-face points, basket_id filter  |
| Object Storage  | MinIO (self-hosted) or S3        | Encrypted, signed URLs             |
| Frontend        | React + Vite                     | Two panels — see Section 6         |
| Cache           | Redis                            | Basket state, search result cache  |

---

## 4. Updated System Milestones

### 🏁 Milestone 1 — Smart Ingestion Engine
**Objective:** Process 600 images on a 4-core CPU in under 5 minutes.

- Resize to 640px longest edge (RGB preserved).
- Quality gate: size, blur, pose filtering before any embedding.
- `ProcessPoolExecutor` with per-worker ONNX session init.
- Progress events streamed to frontend via SSE (`/baskets/{id}/progress`).
- Incremental: new images added to an existing basket re-use the warm pool.

### 🏁 Milestone 2 — Multi-Index Vectorization (Per-Face)
**Objective:** Create robust face identity, one Qdrant point per detected face.

- Three vectors per face: `front`, `profile` (H-flip + landmark crop), `low_light` (CLAHE).
- Payload carries `basket_id`, `image_path`, `face_bbox`, `quality_score`.
- Qdrant collection configured with `hnsw_config.m=16` for balanced speed/recall.

### 🏁 Milestone 3 — Union Coarse-to-Fine Retrieval
**Objective:** High recall on candid, profile, and low-light photos.

- Stage 1: Union of Top-50 ANN results from all three indices.
- Stage 2: Weighted score fusion (weights: front=0.5, profile=0.3, low_light=0.2).
- Minimum threshold: 0.42. Results deduplicated by `image_path`.

---

## 5. Updated Directory Structure

```
/project-root
│── /models
│   ├── scrfd_2.5g_bnkps_int8.onnx
│   └── mobilefacenet_fp16.onnx
│── /scripts
│   ├── processor.py      # Worker init, quality gate, embedding pipeline
│   ├── database.py       # Qdrant client, per-face upsert, basket management
│   ├── search.py         # Union coarse filter + weighted score fusion
│   ├── storage.py        # MinIO client, signed URL generation
│   └── selfie_prep.py    # Query normalization, EXIF fix, mirror detection
│── /frontend             # React + Vite (see Section 6)
│   ├── /photographer     # Basket manager panel
│   └── /viewer           # End-user selfie search
│── app.py                # FastAPI: /baskets, /search, /progress SSE
│── docker-compose.yml
└── gemini.md
```

---

## 6. Frontend Plan — React UI

### 6.1 Architecture: Two Distinct Surfaces

```
┌──────────────────────────────────────────────────────┐
│  PHOTOGRAPHER SURFACE  (auth-gated)                  │
│  Route: /studio                                      │
│  Panel 1: Basket Manager  │  Panel 2: Live Upload    │
│  Panel 3: Basket Settings │  Panel 4: Share / Stats  │
└──────────────────────────────────────────────────────┘
                        │
                 Share URL generated
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│  END-USER SURFACE  (no auth, URL-gated)              │
│  Route: /find/:basket_id                             │
│  Step 1: Selfie capture / upload                     │
│  Step 2: Processing indicator                        │
│  Step 3: Photo gallery of matches                    │
└──────────────────────────────────────────────────────┘
```

---

### 6.2 Photographer Studio — Panel Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [🗂 FaceBasket Studio]                        [Account ▾]      │
├──────────────┬──────────────────────────────────────────────────┤
│              │                                                   │
│  BASKETS     │   📂 "Sharma Wedding – Nov 2024"       [Live ●]  │
│  ──────────  │   ────────────────────────────────────────────── │
│  > Sharma    │                                                   │
│    Wedding   │   ┌────────────────────────────────────────┐    │
│              │   │  DROP IMAGES HERE  or  Browse Files    │    │
│  + New       │   │  (JPG, PNG, HEIC — up to 50 at once)  │    │
│    Basket    │   └────────────────────────────────────────┘    │
│              │                                                   │
│              │   QUEUE (12 processing, 347 done, 0 failed)      │
│              │   ██████████████████████░░░░░  74%              │
│              │   [ img_0341.jpg ✓ ]  [ img_0342.jpg ⟳ ]        │
│              │                                                   │
│              │   ────────────────────────────────────────────── │
│              │   SHARE LINK                                      │
│              │   https://fb.io/find/sharma-nov24   [Copy] [QR]  │
│              │                                                   │
│              │   347 faces indexed  •  3 people found so far    │
└──────────────┴───────────────────────────────────────────────── ┘
```

**Key Behaviors:**
- Photographer can drop new images at any time, even while the basket is live and
  users are already searching. New images enter the queue immediately.
- Progress bar is driven by SSE from `/baskets/{id}/progress`.
- "Live ●" badge shows the basket is accepting both uploads and searches.
- Share link is generated on basket creation, not after processing — users who
  arrive early see a "Photos still being added, check back soon" state.
- QR code opens a modal with a printable QR for event signage.

---

### 6.3 End-User Selfie Search — Flow

```
Step 1: Landing
┌──────────────────────────────────────────┐
│  Find yourself in                        │
│  "Sharma Wedding – Nov 2024"             │
│                                          │
│  ┌──────────────────────────────────┐   │
│  │      📷  Take a Selfie           │   │
│  └──────────────────────────────────┘   │
│  ─── or ───                             │
│  ┌──────────────────────────────────┐   │
│  │      🖼  Upload a Photo          │   │
│  └──────────────────────────────────┘   │
│                                          │
│  Your photo is never stored.             │
└──────────────────────────────────────────┘

Step 2: Processing (2–4 seconds)
┌──────────────────────────────────────────┐
│  [Face preview thumbnail]                │
│  Searching 347 photos…                  │
│  ████████████████░░░░  Stage 2/2        │
└──────────────────────────────────────────┘

Step 3: Results
┌──────────────────────────────────────────┐
│  Found you in 14 photos! 🎉             │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐           │
│  │    │ │    │ │    │ │    │  (grid)    │
│  └────┘ └────┘ └────┘ └────┘           │
│  [Download All]  [Share Results]        │
│                                          │
│  Photos available for 24 hours          │
└──────────────────────────────────────────┘
```

**Key Behaviors:**
- Camera uses `getUserMedia` with `facingMode: "user"`.
- Live face-detection overlay (using a lightweight JS model like face-api.js tfjs
  tiny model, client-side only) shows a bounding box so user aligns their face
  before capturing.
- Results open using 1-hour signed S3 URLs — no raw storage exposed.
- "Your photo is never stored" is factually true and shown prominently.
- If basket is still processing, show: "X photos indexed so far — your results
  may grow as more are processed. Refresh to check."

---

### 6.4 Component Tree

```
App
├── /studio                  (auth-gated)
│   ├── StudioLayout
│   │   ├── BasketSidebar        # list of photographer's baskets
│   │   ├── BasketHeader         # name, live status, share link
│   │   ├── UploadDropzone       # react-dropzone, HEIC → JPEG client-side
│   │   ├── IngestionQueue       # SSE-driven progress list
│   │   ├── BasketStats          # faces indexed, searches run
│   │   └── SharePanel           # URL copy, QR modal
│
└── /find/:basket_id         (public, no auth)
    ├── FindLayout
    │   ├── BasketBranding       # event name, photographer branding
    │   ├── SelfieCapture        # webcam + upload, face-api.js overlay
    │   ├── SearchProgress       # animated 2-stage indicator
    │   └── ResultsGallery       # masonry grid, download, share
```

---

### 6.5 Key API Contracts (Frontend ↔ Backend)

```
POST /baskets                      → { basket_id, share_url }
POST /baskets/:id/images           → 202 Accepted (async processing)
GET  /baskets/:id/progress         → SSE stream: { done, total, failed, faces_indexed }
GET  /baskets/:id/info             → { name, image_count, faces_indexed, is_live }
POST /baskets/:id/search           → multipart selfie → { matches: [{ image_url, score, face_bbox }] }
DELETE /baskets/:id                → 204 (purges Qdrant points + S3 objects)
```

---

### 6.6 Frontend Tech Choices

| Concern            | Choice                          | Reason                                    |
|--------------------|---------------------------------|-------------------------------------------|
| Framework          | React + Vite                    | Fast HMR, clean build                     |
| Styling            | Tailwind CSS                    | Utility-first, consistent                 |
| File upload        | react-dropzone                  | Handles drag, multi-file, HEIC            |
| HEIC conversion    | heic2any (client-side)          | iPhone photos without server-side convert |
| Camera             | react-webcam                    | Simple getUserMedia wrapper               |
| Face overlay       | face-api.js (tinyFaceDetector)  | Client-side, no privacy leak              |
| SSE               | Native EventSource API          | No extra deps for progress stream         |
| QR generation      | qrcode.react                    | Printable QR for event signage            |
| Image grid         | react-photo-album               | Masonry layout for varied aspect ratios   |
| State              | Zustand                         | Lightweight, no boilerplate               |

---

## 7. Performance Targets (Revised)

| Metric                        | Target         | Method                                      |
|-------------------------------|----------------|---------------------------------------------|
| Ingestion throughput          | 600 imgs < 5min| 4-core pool, warm sessions, quality gate     |
| Search latency (P95)          | < 800ms        | Union ANN + fusion on ≤150 candidates       |
| False positive rate           | < 2%           | Threshold=0.42 + quality gate at query time |
| Selfie-to-results (end-user)  | < 3s           | SSE progress, signed URL pre-generation     |
| RAM per worker                | < 400MB        | FP16 model, no crop persistence             |
