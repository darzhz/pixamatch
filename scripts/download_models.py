import os
import requests
from tqdm import tqdm

MODELS_DIR = "models"
MODELS = {
    "scrfd_2.5g_bnkps.onnx": "https://huggingface.co/OwlMaster/AllFilesRope/resolve/main/scrfd_2.5g_bnkps.onnx",
    "mobilefacenet.onnx": "https://github.com/yywbxgl/face_detection/raw/master/models/mobilefacenet.onnx"
}

def download_file(url, dest):
    print(f"Downloading {url} to {dest}...")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024
    t = tqdm(total=total_size, unit='iB', unit_scale=True)
    with open(dest, 'wb') as f:
        for data in response.iter_content(block_size):
            t.update(len(data))
            f.write(data)
    t.close()
    if total_size != 0 and t.n != total_size:
        print("ERROR: Something went wrong during download")

if __name__ == "__main__":
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)
    
    for filename, url in MODELS.items():
        dest = os.path.join(MODELS_DIR, filename)
        if not os.path.exists(dest):
            download_file(url, dest)
        else:
            print(f"{filename} already exists, skipping.")
    
    # Optional renaming for specific project conventions if needed
    # (e.g., if you want scrfd_2.5g_bnkps_int8.onnx or mobilefacenet_fp16.onnx)
    print("Models downloaded successfully.")
