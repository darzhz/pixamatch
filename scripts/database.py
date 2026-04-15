from qdrant_client import QdrantClient
from qdrant_client.http import models
import uuid
import os

class DatabaseClient:
    def __init__(self, host=os.getenv("QDRANT_HOST", "localhost"), port=int(os.getenv("QDRANT_PORT", 6333))):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = "faces"
        self._ensure_collection()

    def _ensure_collection(self):
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "front": models.VectorParams(size=128, distance=models.Distance.COSINE),
                    "profile": models.VectorParams(size=128, distance=models.Distance.COSINE),
                    "low_light": models.VectorParams(size=128, distance=models.Distance.COSINE),
                },
                hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True
                    )
                )
            )

    def upsert_face(self, basket_id, image_path, vectors, bbox, quality_score):
        return self.upsert_faces_batch(basket_id, [{
            "image_path": image_path,
            "vectors": vectors,
            "bbox": bbox,
            "quality_score": quality_score
        }])[0]

    def upsert_faces_batch(self, basket_id, faces_data):
        points = []
        point_ids = []
        for face in faces_data:
            point_id = str(uuid.uuid4())
            points.append(models.PointStruct(
                id=point_id,
                vector=face["vectors"],
                payload={
                    "basket_id": basket_id,
                    "image_path": face["image_path"],
                    "face_bbox": face["bbox"],
                    "quality_score": face["quality_score"]
                }
            ))
            point_ids.append(point_id)
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )
        return point_ids

    def search_faces(self, vector_name, query_vector, basket_id, top=50):
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            using=vector_name,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="basket_id",
                        match=models.MatchValue(value=basket_id)
                    )
                ]
            ),
            limit=top,
            with_payload=True
        ).points
        return results

    def delete_basket(self, basket_id):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="basket_id",
                        match=models.MatchValue(value=basket_id)
                    )
                ]
            )
        )

if __name__ == "__main__":
    # Quick test
    db = DatabaseClient()
    import numpy as np
    dummy_vec = np.random.rand(128).tolist()
    vecs = {"front": dummy_vec, "profile": dummy_vec, "low_light": dummy_vec}
    pid = db.upsert_face("test_basket", "test.jpg", vecs, [0,0,10,10], 0.99)
    print(f"Upserted point: {pid}")
    res = db.search_faces("front", dummy_vec, "test_basket")
    print(f"Search results: {len(res)}")
    db.delete_basket("test_basket")
    print("Deleted test basket")
