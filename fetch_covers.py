#!/usr/bin/env python3
"""Скачать обложки для заметок из Wikimedia Commons (свободные лицензии).

  python3 fetch_covers.py --set zelda-ocarina-switch-2="Nintendo Switch 2 console" \
                            --set pikmin-4-switch-2-demo="Pikmin"

Кладёт файлы в static/img/, печатает готовые строки cover:/credit: для frontmatter.
Лицензию и автора берём из метаданных Commons — их надо указать в credit.
"""
import argparse
import json
import pathlib
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "GEEKOVSKI-blog/1.0 (geekovski@yandex.ru)"}
OUT = pathlib.Path(__file__).resolve().parent / "static" / "img"


def api(params):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))


def find(query, width=1600):
    d = api({"action": "query", "format": "json", "generator": "search",
             "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": "6", "gsrlimit": "5",
             "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": str(width)})
    pages = (d.get("query", {}).get("pages", {}) or {}).values()
    for p in sorted(pages, key=lambda x: x.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        if not ii.get("thumburl"):
            continue
        if "non-free" in lic.lower() or "fair use" in lic.lower():
            continue
        return {"title": p.get("title", ""), "url": ii["thumburl"], "license": lic, "artist": artist}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="SLUG=QUERY")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in a.set:
        slug, _, query = spec.partition("=")
        hit = find(query)
        if not hit:
            print(f"# {slug}: ничего не найдено по «{query}»")
            continue
        ext = ".jpg" if ".jpg" in hit["url"].lower() else (".png" if ".png" in hit["url"].lower() else ".webp")
        name = slug + ext
        data = urllib.request.urlopen(urllib.request.Request(hit["url"], headers=UA), timeout=40).read()
        (OUT / name).write_bytes(data)
        print(f"# {slug}: {hit['title']} — {hit['license']} — {hit['artist'][:60]} — {len(data)//1024} КБ")
        print(f"cover: /assets/img/{name}")
        print(f"credit: {hit['artist'][:80]} / Wikimedia Commons, {hit['license']}")


if __name__ == "__main__":
    main()
