import boto3
from botocore.client import Config
import os

class StorageClient:
    def __init__(self, endpoint="localhost:9000", access_key="minioadmin", secret_key="minioadmin", bucket="pixamatch"):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1" # MinIO default
        )
        self.bucket = bucket
        self._ensure_bucket()

    def _ensure_bucket(self):
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except:
            self.s3.create_bucket(Bucket=self.bucket)

    def upload_image(self, file_path, key):
        self.s3.upload_file(file_path, self.bucket, key)
        return key

    def upload_fileobj(self, fileobj, key):
        self.s3.upload_fileobj(fileobj, self.bucket, key)
        return key

    def get_signed_url(self, key, expires_in=3600):
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in
        )

if __name__ == "__main__":
    # Quick test
    client = StorageClient()
    with open("test.txt", "w") as f:
        f.write("hello pixamatch")
    client.upload_image("test.txt", "test.txt")
    url = client.get_signed_url("test.txt")
    print(f"Test URL: {url}")
    os.remove("test.txt")
