# Pixamatch Technical Specification: High-Efficiency Pipeline

## 1. Overview
Pixamatch is designed to handle bulk image ingestion (up to 1,000 images per batch) on commodity hardware by offloading compute-intensive tasks to the client and utilizing an asynchronous, multi-process backend.

---

## 2. Process Flow

### Phase 1: Client-Side Pre-Processing (Frontend)
1.  **Iterative Queueing**: Images processed in chunks of 3 via `OffscreenCanvas`.
2.  **Normalization**: Resized to 640px, converted to `image/webp` (0.7 quality).
3.  **Batch Upload**: Uploads in chunks of 20, memory cleared immediately.

### Phase 2: Asynchronous Ingestion (Backend)
1.  **Orchestration**: `ProcessPoolExecutor` manages CPU-bound ONNX inference. Workers stay warm with pre-initialized sessions.
2.  **AI Pipeline**:
    *   **Detection**: SCRFD (ONNX INT8).
    *   **Quality Gate**: 
        *   Size: ≥ 40x40px.
        *   Blur: Laplacian variance > 80.
        *   **Pose**: Yaw absolute < 70° (via 5-point landmarks).
    *   **Vectorization**: MobileFaceNet (ONNX FP16). 
        *   `front`: Standard crop.
        *   `profile`: Crop optimized for detected yaw (if yaw > 25°).
        *   `low_light`: CLAHE applied (`clipLimit=2.0`, `tileGridSize=(8,8)`).
3.  **Progress**: Published to Redis Pub/Sub. SSE endpoint subscribes to channel, enabling multi-instance scaling.

### Phase 3: Vector Indexing & Search (Qdrant)
1.  **Batch Upsert**: 256 points per request for throughput.
2.  **Quantization**: INT8 Scalar Quantization active.
3.  **Multi-Index Search**:
    *   **Query**: Selfie capture generates 3 query vectors (q_front, q_profile, q_low_light).
    *   **Coarse Pass**: Union of Top-50 from each index. `hnsw_ef=64`.
    *   **Fine Pass**: Weighted score fusion (0.5/0.3/0.2). `hnsw_ef=128`.
    *   **Threshold**: `MATCH_THRESHOLD = 0.42`. No results returned below this.

---

## 3. Technical Architecture

| Component | Technology | Optimization |
| :--- | :--- | :--- |
| **Frontend** | React + Vite | Web Workers, Selfie Pose Guide |
| **API** | FastAPI + ProcessPool | Multi-process worker pool, Redis Pub/Sub SSE |
| **Inference** | ONNX Runtime | INT8 Detection / FP16 Recognition |
| **Vector DB** | Qdrant | Named Vectors, INT8 Quantization, Tuned `hnsw_ef` |

---

## 4. Performance Targets
*   **Ingestion Rate**: 600+ images in < 5 minutes on 4-core CPU.
*   **Search Latency**: < 800ms for 10k faces.
*   **Accuracy**: High recall on profiles/low-light via multi-index fusion.
