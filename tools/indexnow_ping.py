#!/usr/bin/env python3
"""IndexNow: сообщить Яндексу и Bing о новых/изменённых адресах.

Зачем: GitHub Pages не умеет отдавать «карту изменений», поэтому свежий материал
ждёт обхода от часов до суток. IndexNow доставляет адрес напрямую — это же
ускоряет попадание в индекс Bing, из которого отвечает часть AI-поиска.

  python3 tools/indexnow_ping.py                 # все адреса из docs/sitemap.xml
  python3 tools/indexnow_ping.py <url> [<url>…]  # только эти адреса (до 10 000)

Ключ лежит в static/indexnow-key.txt; build.py кладёт его файлом в корень сайта,
и до деплоя ключа IndexNow отвечает 403 — это нормально, сначала пуш, потом пинг.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://geekovski.ru"
ENDPOINTS = ("https://api.indexnow.org/indexnow", "https://yandex.com/indexnow")


def key():
    return (ROOT / "static" / "indexnow-key.txt").read_text(encoding="utf-8").strip()


def sitemap_urls():
    xml = (ROOT / "docs" / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>(https://geekovski\.ru[^<]+)</loc>", xml)


def ping(urls, endpoint):
    payload = json.dumps({"host": SITE.split("//")[1], "key": key(),
                          "keyLocation": "%s/%s.txt" % (SITE, key()),
                          "urlList": urls}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=payload,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except urllib.error.URLError as e:
        return None, str(e.reason)


def main():
    urls = sys.argv[1:] or sitemap_urls()
    if not urls:
        sys.exit("не нашёл адресов: ни аргументов, ни docs/sitemap.xml")
    urls = [u if u.startswith("http") else SITE + "/" + u.lstrip("/") for u in urls]
    print("ключ %s, адресов: %d" % (key(), len(urls)))
    for endpoint in ENDPOINTS:
        status, body = ping(urls[:10000], endpoint)
        ok = status in (200, 202)
        print("%s → %s %s" % (endpoint, status, "ok" if ok else "ошибка"))
        if body:
            print("   %s" % body.replace("\n", " ")[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
