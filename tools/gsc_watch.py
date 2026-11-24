#!/usr/bin/env python3
"""Сторож индексации: раз в день проверяет пачку страниц через URL Inspection API.

    python3 tools/gsc_watch.py               # очередные 10 адресов (круг за кругом)
    python3 tools/gsc_watch.py --all         # проверить все страницы сайта
    python3 tools/gsc_watch.py --status      # только сводка по сохранённым данным

Зачем: у Search Console нет метода «отправить на индексирование» — только чтение.
Зато `urlInspection.index.inspect` отдаёт вердикт и дату последнего обхода по каждому
адресу. Отсюда и берётся ответ «началась индексация или нет»: считаем PASS/NEUTRAL
и показываем, что изменилось с прошлого прогона.

Состояние: content/seo/gsc-watch.json (в репозитории, чтобы крон и ручные запуски
видели одну картину).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
POSTS = ROOT / "content" / "posts"
STATE = ROOT / "content" / "seo" / "gsc-watch.json"
SITE = "https://geekovski.ru/"

sys.path.insert(0, str(ROOT / "tools"))
import gsc  # noqa: E402

SKIP = ("404.html", "offline.html", "digests/index.html")


def pages() -> list[str]:
    """Все публичные страницы: статьи, рубрики, тайтлы. Без служебок и сборников."""
    out = []
    for path in sorted(DOCS.glob("*.html")):
        if path.name in SKIP:
            continue
        if path.name.startswith("2026-") and any(
                w in path.stem for w in ("-otchet", "-vecher", "-utro", "-kalendar")):
            continue
        out.append(SITE + path.name)
    for folder in ("titles",):
        out.extend(SITE + folder + "/" + p.name for p in sorted((DOCS / folder).glob("*.html")))
    return out


def load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"urls": {}, "pointer": 0, "rounds": 0, "history": []}


def save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def inspect(url: str) -> dict:
    try:
        d = gsc.api("POST", "/v1/urlInspection/index:inspect", {
            "inspectionUrl": url, "siteUrl": gsc.SITE, "languageCode": "ru-RU"},
            scope=gsc.SCOPES["inspect"])
    except SystemExit:
        return {"coverage": "ошибка запроса"}
    st = d.get("inspectionResult", {}).get("indexStatusResult", {})
    return {
        "coverage": st.get("coverageState") or "неизвестно",
        "verdict": st.get("verdict") or "",
        "crawled": (st.get("lastCrawlTime") or "")[:10],
        "canonical": st.get("googleCanonical") or "",
    }


def summary(st: dict) -> str:
    urls = st.get("urls", {})
    if not urls:
        return "индексация: данных ещё нет — запусти проверку"
    total = len(urls)
    indexed = [u for u, v in urls.items() if v.get("verdict") == "PASS"]
    unknown = [u for u, v in urls.items() if "неизвестен" in (v.get("coverage") or "")]
    other = total - len(indexed) - len(unknown)
    lines = ["проверено: %d адресов · в индексе: %d (%.0f%%) · неизвестно Google: %d · прочее: %d"
             % (total, len(indexed), 100 * len(indexed) / total, len(unknown), other)]
    # history[-1] — запись текущего прогона (её пишем перед печатью), поэтому
    # сравниваем с предыдущей
    if len(st.get("history") or []) >= 2:
        prev = st["history"][-2]
        lines.append("с прошлого прогона: в индексе %+d, проверено %+d"
                     % (len(indexed) - prev.get("indexed", 0), total - prev.get("total", 0)))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Сторож индексации Search Console")
    ap.add_argument("--limit", type=int, default=10, help="сколько адресов за прогон")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    st = load()
    if a.status:
        print(summary(st))
        return 0

    queue = pages()
    if a.all:
        batch = queue
    else:
        start = st.get("pointer", 0) % max(len(queue), 1)
        batch = (queue + queue)[start:start + a.limit]
        st["pointer"] = (start + len(batch)) % max(len(queue), 1)

    before = {u for u, v in st["urls"].items() if v.get("verdict") == "PASS"}
    fresh = []
    for url in batch:
        res = inspect(url)
        st["urls"][url] = dict(res, checked=dt.date.today().isoformat())
        if res.get("verdict") == "PASS" and url not in before:
            fresh.append(url)

    indexed = sum(1 for v in st["urls"].values() if v.get("verdict") == "PASS")
    st["rounds"] = st.get("rounds", 0) + 1
    st["history"] = (st.get("history", []) + [{
        "date": dt.date.today().isoformat(), "total": len(st["urls"]), "indexed": indexed,
    }])[-60:]
    save(st)

    print("Индексация GEEKOVSKI · %s" % dt.date.today().strftime("%d.%m"))
    print("в этом прогоне проверено: %d" % len(batch))
    print(summary(st))
    if fresh:
        print("\nвпервые в индексе (%d):" % len(fresh))
        for u in fresh:
            print("  " + u)
    started = [u for u in batch if st["urls"][u].get("crawled")]
    if started and not fresh:
        print("\nGoogle обходил, но индекса ещё нет: %d адресов" % len(started))
    if indexed == 0:
        print("\nиндексация ещё не началась: ни один проверенный адрес не в индексе")
    return 0


if __name__ == "__main__":
    sys.exit(main())
