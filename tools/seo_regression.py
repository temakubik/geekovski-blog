#!/usr/bin/env python3
"""Проверка после редизайна: адреса, заголовки и тексты должны остаться на месте.

Редизайн (Onlook, другой агент) меняет CSS и шаблоны, но не контент. Этот скрипт
сверяет живой сайт с эталоном: все URL на месте, <title> и <h1> не поменялись,
тексты статей не потеряли слов, robots-мета и canonical не сломались.

  python3 tools/seo_regression.py --snapshot   # зафиксировать эталон (сейчас)
  python3 tools/seo_regression.py              # сравнить прод с эталоном

Эталон лежит в tools/seo-baseline.json и коммитится в репозиторий.
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tools" / "seo-baseline.json"
BASE = "https://geekovski.ru"
UA = {"User-Agent": "Mozilla/5.0 (compatible; GEEKOVSKI-audit)"}


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def sitemap_urls():
    _, xml = get(BASE + "/sitemap.xml")
    return sorted(re.findall(r"<loc>([^<]+)</loc>", xml))


def page_facts(url):
    status, html = get(url)
    title = re.search(r"<title>([^<]*)</title>", html)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', html)
    robots = re.search(r'<meta name="robots" content="([^"]*)"', html)
    canon = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    words = len([w for w in re.split(r"\s+", text) if w.strip()])
    return {
        "status": status,
        "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
        "h1": re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else "",
        "desc_len": len(desc.group(1)) if desc else 0,
        "robots": robots.group(1) if robots else "",
        "canonical": canon.group(1) if canon else "",
        "words": words,
    }


def snapshot():
    urls = sitemap_urls()
    data = {}
    for i, u in enumerate(urls, 1):
        try:
            data[u] = page_facts(u)
        except Exception as e:
            data[u] = {"error": str(e)[:80]}
        if i % 25 == 0:
            print("  снято", i, "из", len(urls), flush=True)
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("эталон сохранён:", len(data), "адресов →", BASELINE)


def compare():
    if not BASELINE.exists():
        sys.exit("нет эталона: сначала запусти с --snapshot")
    old = json.loads(BASELINE.read_text(encoding="utf-8"))
    now = sitemap_urls()
    problems = []

    for u in old:
        if u not in now:
            problems.append(("АДРЕС ПРОПАЛ", u))
    for u in now:
        if u not in old:
            print("новый адрес (норма):", u)

    for u, was in old.items():
        if u not in now or "error" in was:
            continue
        try:
            cur = page_facts(u)
        except urllib.error.HTTPError as e:
            problems.append(("HTTP %s" % e.code, u))
            continue
        except Exception as e:
            problems.append(("ОШИБКА " + str(e)[:40], u))
            continue
        if cur["status"] != 200:
            problems.append(("не 200 (%s)" % cur["status"], u))
        if was["title"] and cur["title"] != was["title"]:
            problems.append(("сменился TITLE: «%s» → «%s»" % (was["title"][:50], cur["title"][:50]), u))
        if was["h1"] and cur["h1"] != was["h1"]:
            problems.append(("сменился H1: «%s» → «%s»" % (was["h1"][:40], cur["h1"][:40]), u))
        if "noindex" in cur["robots"] and "noindex" not in was["robots"]:
            problems.append(("появился NOINDEX", u))
        if was["canonical"] and cur["canonical"] != was["canonical"]:
            problems.append(("сменился CANONICAL", u))
        if was["words"] and cur["words"] < was["words"] * 0.9:
            problems.append(("текст усох: %d → %d слов" % (was["words"], cur["words"]), u))

    print()
    if not problems:
        print("OK: адреса, заголовки и тексты на месте")
    else:
        print("НАЙДЕНО ПРОБЛЕМ:", len(problems))
        for kind, u in problems:
            print("  •", kind, "—", u)
    return 0 if not problems else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args()
    if a.snapshot:
        snapshot()
    else:
        sys.exit(compare())
