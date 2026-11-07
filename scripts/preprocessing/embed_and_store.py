import json
from pathlib import Path

import chromadb
import yaml
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
CHUNKS_FILE = ROOT / "data" / "chunks" / "chunks.jsonl"
DB_DIR = ROOT / SETTINGS["vectorstore"]["path"]
COLLECTION = SETTINGS["vectorstore"]["collection"]
BATCH_SIZE = 16


def load_chunks():
    """Read chunks.jsonl, one JSON object per line."""
    with CHUNKS_FILE.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks")

    model_name = SETTINGS["embedding"]["model"]
    print(f"Loading embedding model {model_name} (first run downloads about 2 GB)...")
    model = SentenceTransformer(model_name)

    texts = [c["text"] for c in chunks]
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,   # makes cosine similarity work properly
        show_progress_bar=True,
    )

    client = chromadb.PersistentClient(path=str(DB_DIR))

    # start fresh each run, so old chunks never linger
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=[c["id"] for c in chunks],
        documents=texts,
        embeddings=embeddings.tolist(),
        metadatas=[{
            "url": c["url"] or "",          # Chroma doesn't accept None
            "type": c["type"],
            "title": c["title"],
            "heading": c["heading"] or "",
        } for c in chunks],
    )

    print(f"Stored {collection.count()} chunks in {DB_DIR} (collection '{COLLECTION}')")


if __name__ == "__main__":
    main()