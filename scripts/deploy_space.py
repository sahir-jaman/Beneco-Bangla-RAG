from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]      # scripts/ -> project folder
SPACE_ID = "sahir-zaman/beneco-bangla-chatbot"

api = HfApi()   # uses your browser login

# 1. create the Space (does nothing if it already exists)
api.create_repo(SPACE_ID, repo_type="space", space_sdk="docker",
                private=True, exist_ok=True)
print("Space ready:", SPACE_ID)

# 2. give the Space its runtime token as a secret (never uploaded as a file)
runtime_token = dotenv_values(ROOT / ".env")["HF_TOKEN"]
api.add_space_secret(SPACE_ID, "HF_TOKEN", runtime_token)
print("Secret HF_TOKEN set")

# 3. upload only what the running bot needs
api.upload_folder(
    folder_path=ROOT,
    repo_id=SPACE_ID,
    repo_type="space",
    allow_patterns=["app/**", "config/**", "chroma_db/**",
                    "requirements.txt", "Dockerfile", "README.md"],
    ignore_patterns=["**/__pycache__/**"],
)
print(f"Uploaded. Watch the build at https://huggingface.co/spaces/{SPACE_ID}")