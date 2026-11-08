import os
from pathlib import Path

import chromadb
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

from app.leads import empty_lead, lead_summary, update_lead

ROOT = Path(__file__).resolve().parents[1]     # app/ -> project folder
load_dotenv(ROOT / ".env")

REWRITE_PROMPT = """You turn customer messages into search queries for the website of
Beneco Financial Services, a UK mortgage, insurance and business finance broker.
The message may be in Bangla, Banglish (Bangla written in English letters) or English.
If a conversation is given, use it to understand what the latest message refers to
(for example "this", "eta", "oita", "how much for that").

Common Banglish and Bangla words:
- sud, shud, সুদ = interest. "sud dite chai na" = wants interest-free, Sharia-compliant (Islamic) finance
- bari, বাড়ি = house, home. bari kinte = buy a house
- dokan, দোকান = shop. byabsa, business, ব্যবসা = business
- lon, loan, লোন, rin, ঋণ = loan. taka, টাকা = money
- kisti, কিস্তি = monthly payment, instalment
- bima, বীমা = insurance. osustho = sick, ill
- bhara, ভাড়া = rent. bhara dewar jonno = buy-to-let

Write ONE short English search query that captures what the customer wants now.
Use clear financial terms where they fit, for example: first-time buyer, mortgage,
remortgage, home mover, buy-to-let, Sharia-compliant no-interest finance, bridging loan,
deposit, fees, life insurance, income protection, business loan, asset finance,
contact details, office address, opening hours.
If the message only gives a name, phone number or email, output: contact details
If the message is only a greeting, thanks or small talk (hi, hello, kemon asen, dhonnobad), output: greeting
If the message asks for a joke, a fun fact, or is chit-chat not about money, homes, insurance or business, output: small talk
Output only the query, nothing else."""


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

        # how many earlier messages the bot looks at
        self.max_history = s.get("memory", {}).get("max_history_messages", 6)

    def _chat(self, messages, max_tokens):
        """One LLM call; retries once if the reply comes back empty."""
        llm_cfg = self.settings["llm"]
        for attempt in range(2):
            response = self.llm.chat.completions.create(
                model=llm_cfg["model"],
                temperature=llm_cfg["temperature"],
                max_tokens=max_tokens,
                messages=messages,
            )
            choice = response.choices[0]
            text = (choice.message.content or "").strip()
            print(f"LLM attempt={attempt + 1} finish_reason={choice.finish_reason} "
                  f"chars={len(text)}", flush=True)
            if text:
                return text
        return ""

    def _recent(self, history):
        """Keep only the last few messages, in the format the LLM expects."""
        recent = []
        for m in (history or [])[-self.max_history:]:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                recent.append({"role": m["role"], "content": m["content"]})
        return recent

    def rewrite_query(self, question, history=None):
        """Add an English search query to the original message, using the conversation."""
        recent = self._recent(history)
        if recent:
            conversation = "\n".join(
                f"{'Customer' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in recent
            )
            user_text = f"CONVERSATION:\n{conversation}\n\nLATEST MESSAGE: {question}"
        else:
            user_text = question

        try:
            english = self._chat(
                [{"role": "system", "content": REWRITE_PROMPT},
                 {"role": "user", "content": user_text}],
                max_tokens=self.settings["llm"].get("rewrite_max_tokens", 1500),
            )
        except Exception:
            english = ""            # if the rewrite fails, search with the original only
        return f"{question}\n{english}" if english else question

    def retrieve(self, search_text):
        """Find the best chunks: threshold, source priority, max 2 per page."""
        r = self.settings["retrieval"]
        threshold = r["similarity_threshold"]

        vector = self.embedder.encode([search_text], normalize_embeddings=True).tolist()
        results = self.collection.query(query_embeddings=vector, n_results=r["top_k"] * 3)

        priority = r.get("source_priority", {})
        exclude = set(r.get("exclude_types", []))
        candidates = []
        for doc, meta, distance in zip(results["documents"][0],
                                       results["metadatas"][0],
                                       results["distances"][0]):
            if meta["type"] in exclude:          # e.g. skip old blog posts
                continue
            score = 1 - distance
            bonus = 0.02 * priority.get(meta["type"], 0)   # service pages beat blogs
            candidates.append({"text": doc, "meta": meta,
                               "score": score, "rank_score": score + bonus})

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

    def answer(self, question, history=None, lead=None):
        """Rewrite, retrieve, then ask the LLM with the recent conversation."""
        search_text = self.rewrite_query(question, history)
        chunks = self.retrieve(search_text)

        context = "\n\n".join(
            f"[{i}] {c['meta']['title']} ({c['meta']['url'] or 'Beneco official'})\n{c['text']}"
            for i, c in enumerate(chunks, start=1)
        )
        messages = (
            [{"role": "system", "content": f"{self.system_prompt}\n\n{lead_summary(lead)}"}]
            + self._recent(history)
            + [{"role": "user",
                "content": f"CONTEXT:\n{context or '(empty)'}\n\nQUESTION: {question}"}]
        )
        answer = self._chat(messages, max_tokens=self.settings["llm"]["max_tokens"])
        if not answer:
            answer = self.settings["rules"]["fallback_message"]

        # show only clearly relevant sources, service pages first, max 3
        min_score = self.settings["retrieval"].get("source_min_score", 0.55)
        shown = [c for c in chunks if c["score"] >= min_score]
        ordered = sorted(shown, key=lambda c: c["meta"]["type"] == "blog")
        sources = list(dict.fromkeys(c["meta"]["url"] for c in ordered if c["meta"]["url"]))[:3]

        return {"answer": answer, "sources": sources,
                "used_llm": True, "search_query": search_text}


if __name__ == "__main__":
    print("Loading...")
    rag = BanglaRAG()
    print("Ready. Ask a question (empty line to quit).")
    history = []                                   # terminal memory for testing
    lead = empty_lead()                            # terminal customer record
    while True:
        question = input("\nপ্রশ্ন: ").strip()
        if not question:
            break
        lead, new_contact = update_lead(lead, question, history)
        result = rag.answer(question, history, lead)
        print("  search:", result["search_query"].replace("\n", " | "))
        print("  lead:", lead, "| new contact!" if new_contact else "")
        print("\n" + result["answer"])
        for url in result["sources"]:
            print("  source:", url)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": result["answer"]})
