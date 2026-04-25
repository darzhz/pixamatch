import boto3
from botocore.client import Config
import os

class StorageClient:
    def __init__(self, 
                 endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"), 
                 access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"), 
                 secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"), 
                 bucket=os.getenv("MINIO_BUCKET", "pixamatch"),
                 public_endpoint=os.getenv("MINIO_PUBLIC_ENDPOINT", None)):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1" # MinIO default
        )
        self.bucket = bucket
        # self.s3 is for internal operations (uploads, etc.)
        self.internal_endpoint = f"http://{endpoint}"
        self.public_endpoint = public_endpoint
        
        # self.signer is specifically for generating presigned URLs with the public hostname
        # so that the Host header in the signature matches what the browser hits.
        public_url = f"http://{public_endpoint}" if public_endpoint else self.internal_endpoint
        self.signer = boto3.client(
            "s3",
            endpoint_url=public_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={'addressing_style': 'path'}),
            region_name="us-east-1"
        )
        
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
        url = self.signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in
        )
        print(f"[DEBUG] raw presigned: {url}", flush=True)
        if self.public_endpoint:
            url = url.replace(self.internal_endpoint, f"https://{self.public_endpoint}")
        print(f"[DEBUG] public presigned: {url}", flush=True)
        return url

    def list_images(self, basket_id, limit=50, marker=None):
        params = {
            "Bucket": self.bucket,
            "Prefix": f"{basket_id}/",
            "MaxKeys": limit
        }
        if marker:
            params["Marker"] = marker
        
        response = self.s3.list_objects(**params)
        contents = response.get("Contents", [])
        
        keys = [obj["Key"] for obj in contents]
        next_marker = response.get("NextMarker") or (keys[-1] if response.get("IsTruncated") else None)
        
        return keys, next_marker

    def delete_basket(self, basket_id):
        """Purge all objects in the bucket with the prefix basket_id/"""
        # S3 delete_objects can handle up to 1000 keys at once
        paginator = self.s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.bucket, Prefix=f"{basket_id}/")
        
        for page in pages:
            if 'Contents' in page:
                delete_keys = [{'Key': obj['Key']} for obj in page['Contents']]
                self.s3.delete_objects(Bucket=self.bucket, Delete={'Objects': delete_keys})
        
        return True

    def delete_image(self, key):
        """Remove a single image from storage"""
        self.s3.delete_object(Bucket=self.bucket, Key=key)
        return True

if __name__ == "__main__":
    # Quick test
    client = StorageClient()
    with open("test.txt", "w") as f:
        f.write("hello pixamatch")
    client.upload_image("test.txt", "test.txt")
    url = client.get_signed_url("test.txt")
    print(f"Test URL: {url}")
    os.remove("test.txt")
