import json
import re
from collections import Counter
from pathlib import Path

import yaml
from langchain_text_splitters import RecursiveCharacterTextSplitter

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
CLEAN_DIR = ROOT / "data" / "clean"
MANUAL_DIR = ROOT / "data" / "manual"
CHUNKS_FILE = ROOT / "data" / "chunks" / "chunks.jsonl"

HEADING = re.compile(r"^(#{1,4}) (.+)$")   # matches "## Some heading"


def load_clean_pages(min_words):
    """Load cleaned website pages, skipping near-empty ones."""
    docs = []
    for f in sorted(CLEAN_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if len(d["text"].split()) < min_words:
            continue
        d["source"] = f.stem
        docs.append(d)
    return docs


def load_manual_docs():
    """Load hand-written Markdown files from data/manual (except README)."""
    docs = []
    for f in sorted(MANUAL_DIR.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        raw = f.read_text(encoding="utf-8")
        meta, body = {}, raw
        if raw.startswith("---"):                  # read the header block
            _, front, body = raw.split("---", 2)
            meta = yaml.safe_load(front) or {}
        docs.append({
            "url": None,
            "type": "manual",
            "lastmod": str(meta.get("last_updated", "")),
            "title": meta.get("title", f.stem),
            "text": body.strip(),
            "source": f"manual-{f.stem}",
        })
    return docs


def split_into_sections(text):
    """Split a page into (heading, body) pairs using the ## heading lines."""
    sections, heading, lines = [], "", []
    for line in text.split("\n"):
        match = HEADING.match(line)
        if match:
            if lines:
                sections.append((heading, "\n".join(lines)))
            heading, lines = match.group(2), []
        else:
            lines.append(line)
    if lines:
        sections.append((heading, "\n".join(lines)))
    return sections


def main():
    chunk_cfg = SETTINGS["chunking"]
    min_words = SETTINGS.get("cleaning", {}).get("min_words_to_index", 50)
    min_chars = chunk_cfg.get("min_chunk_chars", 0)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_cfg["chunk_size"],
        chunk_overlap=chunk_cfg["chunk_overlap"],
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    docs = load_clean_pages(min_words) + load_manual_docs()

    chunks = []
    skipped = 0
    for doc in docs:
        n = 0
        for heading, body in split_into_sections(doc["text"]):
            for piece in splitter.split_text(body):
                if len(piece) < min_chars:          # too short to be useful
                    skipped += 1
                    continue
                label = doc["title"] + (f" > {heading}" if heading else "")
                chunks.append({
                    "id": f"{doc['source']}-{n}",
                    "url": doc["url"],
                    "type": doc["type"],
                    "title": doc["title"],
                    "heading": heading,
                    "text": f"{label}\n{piece}",
                })
                n += 1

    CHUNKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_FILE.open("w", encoding="utf-8") as out:
        for chunk in chunks:
            out.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # summary
    doc_types = Counter(d["type"] for d in docs)
    chunk_types = Counter(c["type"] for c in chunks)
    avg_len = sum(len(c["text"]) for c in chunks) // max(len(chunks), 1)
    print(f"Documents used: {dict(doc_types)}")
    print(f"Chunks created: {len(chunks)} {dict(chunk_types)}")
    print(f"Average chunk length: {avg_len} characters")
    print(f"Skipped tiny pieces: {skipped}")
    print(f"Saved to {CHUNKS_FILE}")

    # quality check: show a real remortgage chunk (not a tiny one)
    sample = next((c for c in chunks
                   if c["id"].startswith("remortgage-") and len(c["text"]) > 300), None)
    if sample:
        print("\n--- sample chunk ---")
        print(sample["text"])


if __name__ == "__main__":
    main()