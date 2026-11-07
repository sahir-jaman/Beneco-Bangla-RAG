from pathlib import Path

import chromadb
import yaml
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
DB_DIR = ROOT / SETTINGS["vectorstore"]["path"]
COLLECTION = SETTINGS["vectorstore"]["collection"]
TOP_K = SETTINGS["retrieval"]["top_k"]


def search(model, collection, question):
    """Embed the question and return the closest chunks."""
    query_vector = model.encode([question], normalize_embeddings=True).tolist()
    return collection.query(query_embeddings=query_vector, n_results=TOP_K)


def show(results):
    """Print each result with its similarity score."""
    for rank, (doc, meta, distance) in enumerate(zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]), start=1):
        similarity = 1 - distance          # Chroma gives distance; similarity is easier to read
        preview = doc.replace("\n", " ")[:150]
        print(f"\n[{rank}] score {similarity:.3f} | {meta['type']} | {meta['title']}")
        print(f"    {meta['url']}")
        print(f"    {preview}...")


def main():
    print("Loading model and database...")
    model = SentenceTransformer(SETTINGS["embedding"]["model"])
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection(COLLECTION)
    print(f"Ready: {collection.count()} chunks. Type a question (empty line to quit).")

    while True:
        question = input("\nপ্রশ্ন / question: ").strip()
        if not question:
            break
        show(search(model, collection, question))


if __name__ == "__main__":
    main()