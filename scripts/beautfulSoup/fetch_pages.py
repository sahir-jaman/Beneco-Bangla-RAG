import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
URLS_FILE = ROOT / "data" / "urls.json"
RAW_DIR = ROOT / "data" / "raw"

HEADERS = {"User-Agent": "BenecoBanglaRAG/0.1"}


def url_to_filename(url):
    """Turn a URL into a safe file name, e.g. /buy-to-let/ -> buy-to-let.json"""
    path = urlparse(url).path.strip("/")
    slug = path.replace("/", "__") or "home"
    return f"{slug}.json"


def fetch_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urls = json.loads(URLS_FILE.read_text())
    delay = SETTINGS["website"].get("request_delay_seconds", 1)

    saved = skipped = failed = 0
    for i, item in enumerate(urls, start=1):
        out_file = RAW_DIR / url_to_filename(item["url"])

        # already downloaded on a previous run -> skip it
        if out_file.exists():
            skipped += 1
            continue

        try:
            html = fetch_page(item["url"])
        except requests.RequestException as error:
            print(f"[{i}/{len(urls)}] FAILED {item['url']} -> {error}")
            failed += 1
            continue

        record = {
            **item,  # url, type, lastmod from urls.json
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "html": html,
        }
        out_file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        saved += 1
        print(f"[{i}/{len(urls)}] saved {out_file.name}")

        time.sleep(delay)  # be polite to the website

    print(f"\nDone. saved: {saved}, already had: {skipped}, failed: {failed}")


if __name__ == "__main__":
    main()