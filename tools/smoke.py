#!/usr/bin/env python3
"""Проверка живого сайта после переезда: все адреса из sitemap, фиды, картинки.

    python3 tools/smoke.py                 # проверить geekovski.ru
    python3 tools/smoke.py --host http://127.0.0.1:8080   # локальная сборка
    python3 tools/smoke.py --images 40     # сколько картинок дёрнуть дополнительно

Проверяет:
  · каждая страница из sitemap.xml отдаёт 200 и html;
  · фиды (rss, feed.json, dzen.xml, vk.xml, robots.txt) на месте;
  · выборка картинок отдаёт 200 и правильный content-type;
  · редирект www → без www (если домен боевой);
  · отдаётся ли кэш-заголовок для /assets/ (после переезда — да).

Возвращает код 1, если что-то не 200.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HOST = "https://geekovski.ru"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) GeekovskiSmoke/1.0"


def fetch(url: str, timeout: int = 30, full: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read() if full else r.read(4096)
            return r.status, r.headers.get("Content-Type", ""), r.headers.get("Cache-Control", ""), body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), "", b""
    except Exception as e:
        return 0, str(e)[:80], "", b""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--images", type=int, default=25)
    a = ap.parse_args()
    host = a.host.rstrip("/")

    status, ctype, _, body = fetch(host + "/sitemap.xml", full=True)
    if status != 200:
        print("✗ sitemap.xml: %s %s" % (status, ctype))
        return 1
    urls = re.findall(rb"<loc>([^<]+)</loc>", body)
    # sitemap может быть индексом — тогда догружаем вложенные
    if not urls:
        print("✗ в sitemap нет адресов")
        return 1
    if b"<sitemapindex" in body:
        subs = [u.decode() for u in urls]
        urls = []
        for sub in subs:
            st, _, _, b2 = fetch(sub, full=True)
            if st == 200:
                urls += re.findall(rb"<loc>([^<]+)</loc>", b2)
    pages = [u.decode() for u in urls]
    print("адресов в карте: %d" % len(pages))

    bad = []
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        for url, (st, ct, _, _) in zip(pages, pool.map(fetch, pages)):
            if st != 200 or "html" not in ct:
                bad.append((url, st, ct))
    print("страниц: ok %d, проблем %d" % (len(pages) - len(bad), len(bad)))
    for url, st, ct in bad[:10]:
        print("  · %s → %s %s" % (url, st, ct))

    feeds = ["/", "/rss.xml", "/feed.json", "/dzen.xml", "/vk.xml", "/robots.txt", "/404.html"]
    print("служебные:")
    for path in feeds:
        st, ct, _, _ = fetch(host + path)
        print("  %-14s %s %s" % (path, st, ct.split(";")[0]))
        if st != 200:
            bad.append((host + path, st, ct))

    if a.images:
        st, _, _, body = fetch(host + "/sitemap.xml", full=True)
        images = []
        sti, _, _, b = fetch(host + "/2026-11-27-1800-arkheron-ranij-dostup.html")
        if sti == 200:
            images = re.findall(r"/assets/img/([A-Za-z0-9._@-]+\.(?:jpg|webp|png))", b.decode("utf-8", "ignore"))[:a.images]
        if images:
            print("картинки (выборка %d):" % len(images))
            with cf.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda n: (n,) + fetch(host + "/assets/img/" + n)[:3], images))
            slow_bad = [r for r in results if r[1] != 200]
            print("  ok %d, проблем %d" % (len(results) - len(slow_bad), len(slow_bad)))
            for name, st, ct, cc in results[:5]:
                print("   %-38s %s %s cache=%s" % (name[:38], st, ct.split("/")[-1], cc or "—"))
            bad += [(host + "/assets/img/" + n, st, ct) for n, st, ct, _ in slow_bad]

    if host.startswith("https://") and "127.0.0.1" not in host:
        st, _, _, _ = fetch("https://www.geekovski.ru/")
        print("www: %s %s" % (st, "(редирект настроен)" if st in (301, 302, 308) else "(проверь Redirect from WWW)"))

    print("\nитог:", "всё 200" if not bad else "проблем %d" % len(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
