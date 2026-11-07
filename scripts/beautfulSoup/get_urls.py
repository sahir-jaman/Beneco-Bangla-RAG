import json
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
OUTPUT = ROOT / "data" / "urls.json"

HEADERS = {"User-Agent": "BenecoBanglaRAG/0.1"}


def fetch_xml(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "xml")


def get_sitemap_urls(index_url):
    """Read the sitemap index and return every page URL with its type."""
    index = fetch_xml(index_url)
    results = []
    for sitemap in index.find_all("sitemap"):
        sitemap_url = sitemap.loc.text
        page_type = "blog" if "post-sitemap" in sitemap_url else "page"
        sitemap_xml = fetch_xml(sitemap_url)
        for url in sitemap_xml.find_all("url"):
            results.append({
                "url": url.loc.text,
                "type": page_type,
                "lastmod": url.lastmod.text if url.lastmod else None,
            })
    return results


def should_skip(url, patterns):
    return any(pattern in url for pattern in patterns)


def main():
    website = SETTINGS["website"]
    urls = get_sitemap_urls(website["sitemap_url"])

    for extra in website.get("extra_urls", []):
        urls.append({"url": extra, "type": "page", "lastmod": None})

    skip = website.get("skip_url_patterns", [])
    kept = [u for u in urls if not should_skip(u["url"], skip)]

    # remove duplicates, keeping the first occurrence
    seen, unique = set(), []
    for u in kept:
        if u["url"] not in seen:
            seen.add(u["url"])
            unique.append(u)

    OUTPUT.write_text(json.dumps(unique, indent=2, ensure_ascii=False))

    pages = sum(1 for u in unique if u["type"] == "page")
    blogs = sum(1 for u in unique if u["type"] == "blog")
    print(f"Found {len(urls)} URLs, kept {len(unique)}")
    print(f"  pages: {pages}, blog posts: {blogs}")
    print(f"Saved to {OUTPUT}")


if __name__ == "__main__":
    main()