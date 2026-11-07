import os
from pathlib import Path

import chromadb
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]     # app/ -> project folder
load_dotenv(ROOT / ".env")


class BanglaRAG:
    def __init__(self):
        self.settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
        s = self.settings

        # system prompt with contact details filled in
        contact = s["contact"]
        prompt = (ROOT / "config" / "system_prompt.md").read_text(encoding="utf-8")
        self.system_prompt = prompt.format(
            contact_phone=contact["phone"],
            contact_email=contact["email"],
            booking_link=contact["booking_link"],
        )

        # embedding model + vector database
        self.embedder = SentenceTransformer(s["embedding"]["model"])
        db = chromadb.PersistentClient(path=str(ROOT / s["vectorstore"]["path"]))
        self.collection = db.get_collection(s["vectorstore"]["collection"])

        # LLM client (any OpenAI-compatible provider)
        self.llm = OpenAI(base_url=s["llm"]["base_url"],
                          api_key=os.environ[s["llm"]["api_key_env"]])

    def retrieve(self, question):
        """Find the best chunks: threshold, source priority, max 2 per page."""
        r = self.settings["retrieval"]
        threshold = r["similarity_threshold"]

        vector = self.embedder.encode([question], normalize_embeddings=True).tolist()
        results = self.collection.query(query_embeddings=vector, n_results=r["top_k"] * 3)

        priority = r.get("source_priority", {})
        candidates = []
        for doc, meta, distance in zip(results["documents"][0],
                                       results["metadatas"][0],
                                       results["distances"][0]):
            score = 1 - distance
            bonus = 0.02 * priority.get(meta["type"], 0)   # service pages beat blogs
            candidates.append({"text": doc, "meta": meta,
                               "score": score, "rank_score": score + bonus})

        # off-topic: even the best match is too weak
        if not candidates or candidates[0]["score"] < threshold:
            return []

        candidates.sort(key=lambda c: c["rank_score"], reverse=True)
        per_page, picked = {}, []
        for c in candidates:
            if c["score"] < threshold:
                continue
            key = c["meta"]["url"] or c["meta"]["title"]
            if per_page.get(key, 0) >= r.get("max_chunks_per_page", 2):
                continue
            per_page[key] = per_page.get(key, 0) + 1
            picked.append(c)
            if len(picked) == r["top_k"]:
                break
        return picked

    def answer(self, question):
        """Retrieve chunks, then ask the LLM. Returns answer text and sources."""
        chunks = self.retrieve(question)
        if not chunks:
            return {"answer": self.settings["rules"]["fallback_message"],
                    "sources": [], "used_llm": False}

        context = "\n\n".join(
            f"[{i}] {c['meta']['title']} ({c['meta']['url'] or 'Beneco official'})\n{c['text']}"
            for i, c in enumerate(chunks, start=1)
        )
        llm_cfg = self.settings["llm"]
        response = self.llm.chat.completions.create(
            model=llm_cfg["model"],
            temperature=llm_cfg["temperature"],
            max_tokens=llm_cfg["max_tokens"],
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"},
            ],
        )

        ordered = sorted(chunks, key=lambda c: c["meta"]["type"] == "blog")   # non-blog first
        sources = list(dict.fromkeys(c["meta"]["url"] for c in ordered if c["meta"]["url"]))[:3]
        return {"answer": response.choices[0].message.content,
                "sources": sources, "used_llm": True}


if __name__ == "__main__":
    print("Loading...")
    rag = BanglaRAG()
    print("Ready. Ask a question (empty line to quit).")
    while True:
        question = input("\nপ্রশ্ন: ").strip()
        if not question:
            break
        result = rag.answer(question)
        print("\n" + result["answer"])
        for url in result["sources"]:
            print("  source:", url)