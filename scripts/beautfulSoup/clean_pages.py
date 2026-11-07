import json
import re
from collections import Counter
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "clean"

# tags that never contain useful text
REMOVE_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "header", "footer", "nav"]
# WordPress/Elementor site header, footer and pop-ups
REMOVE_SELECTORS = [
    '[data-elementor-type="header"]',
    '[data-elementor-type="footer"]',
    '[data-elementor-type="popup"]',
]
# tags that start a new line of text
BLOCK_TAGS = ["p", "div", "li", "section", "article", "blockquote", "tr", "td",
              "h1", "h2", "h3", "h4", "h5", "h6"]
# button and link text with no meaning on its own
JUNK_LINES = {"read more", "contact us", "submit", "skip to content",
              "scroll to top", "book appointment", "need help?",
              "related posts", "leave a comment cancel reply", "click here",
              "portfolio", "testimonials"}


def clean_title(soup):
    """'Remortgage - Beneco Finance' or 'X | Beneco Finance' -> 'Remortgage' / 'X'"""
    title = soup.title.get_text(strip=True) if soup.title else ""
    title = re.split(r"\s[|\-–]\s", title)[0]
    return title.strip()


def html_to_lines(html):
    """Turn one page's HTML into a title and a list of clean text lines."""
    soup = BeautifulSoup(html, "lxml")
    title = clean_title(soup)

    # 1. delete everything that isn't content
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()
    for selector in REMOVE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # 2. mark headings Markdown-style, so we keep the page structure
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        level = int(heading.name[1])
        heading.string = "#" * level + " " + heading.get_text(" ", strip=True)

    # 3. put a line break around block elements (but not inside a sentence)
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")

    # 4. get the text and tidy each line
    body = soup.body or soup
    lines = []
    for line in body.get_text().split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 4:
            continue                      # "01", "0+", empty lines
        if not re.search(r"[A-Za-z]", line):
            continue                      # "★★★★★", "‹›"
        if line.lower().lstrip("# ") in JUNK_LINES:
            continue
        lines.append(line)
    return title, lines


def main():
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    min_pages = SETTINGS.get("cleaning", {}).get("boilerplate_min_pages", 4)

    # pass 1: extract the lines of every page
    pages = []
    for raw_file in sorted(RAW_DIR.glob("*.json")):
        record = json.loads(raw_file.read_text(encoding="utf-8"))
        title, lines = html_to_lines(record["html"])
        pages.append({"file": raw_file.name, "record": record, "title": title, "lines": lines})

    # pass 2: find lines that repeat across many pages
    counts = Counter()
    for page in pages:
        counts.update(set(page["lines"]))   # set = count each page only once
    boilerplate = {line for line, n in counts.items() if n >= min_pages}

    # pass 3: save each page without the repeated lines
    short_pages = []
    for page in pages:
        kept = [line for line in page["lines"] if line not in boilerplate]
        text = "\n".join(kept)
        record = page["record"]
        out = {
            "url": record["url"],
            "type": record["type"],
            "lastmod": record.get("lastmod"),
            "title": page["title"],
            "text": text,
        }
        (CLEAN_DIR / page["file"]).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        if len(text.split()) < 50:
            short_pages.append(page["file"])

    # save the repeated lines once, in their original order
    shared, seen = [], set()
    for page in pages:
        for line in page["lines"]:
            if line in boilerplate and line not in seen:
                seen.add(line)
                shared.append(line)
    shared_doc = {
        "url": "https://benecofinance.co.uk/",
        "type": "shared",
        "lastmod": None,
        "title": "Shared website content",
        "text": "\n".join(shared),
    }
    (CLEAN_DIR / "_shared.json").write_text(
        json.dumps(shared_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Cleaned {len(pages)} pages -> {CLEAN_DIR}")
    print(f"Repeated lines moved to _shared.json: {len(shared)}")
    if short_pages:
        print(f"Pages with under 50 words: {len(short_pages)} (skipped when indexing)")


if __name__ == "__main__":
    main()