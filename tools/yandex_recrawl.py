#!/usr/bin/env python3
"""Отправка страниц на переобход в Яндекс.Вебмастер.

    python3 tools/yandex_recrawl.py --dry-run        # показать очередь, ничего не отправлять
    python3 tools/yandex_recrawl.py --limit 10       # отправить до 10 адресов
    python3 tools/yandex_recrawl.py --only 2026-11-24-2100-tarkov-unity-6

Берёт токен и host_id из ~/.hermes/profiles/geekovski/analytics.json (его пишет
tools/yandex_auth.py). Порядок очереди: сегодняшние статьи → вчерашние → те, что
ещё не в поиске. Старые материалы не трогаем: они уже обойдены.

Про 504: API Вебмастера умеет отвечать 504 на recrawl/queue, пока остальные методы
работают. Скрипт делает три попытки с паузой; если не пробилось — печатает адреса
списком, чтобы отправить их кнопкой в кабинете.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
DOCS = ROOT / "docs"
CONF = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / "analytics.json"
SITE = "https://geekovski.ru"
API = "https://api.webmaster.yandex.net/v4/user/%s/hosts/%s"
SENT = ROOT / "content" / "yandex" / "recrawl.json"
SERVICE = re.compile(r"(?:^|/)(?:\d{4}-\d{2}-\d{2}-)?(?:otchet|vecher|utro|kalendar)$")


def conf() -> dict:
    if not CONF.exists():
        raise SystemExit("нет %s — сначала tools/yandex_auth.py" % CONF)
    return json.loads(CONF.read_text(encoding="utf-8"))


def call(token: str, url: str, payload: dict | None = None, method="GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "OAuth " + token,
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def sent_state() -> dict:
    if SENT.exists():
        try:
            return json.loads(SENT.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def save_state(d: dict) -> None:
    SENT.parent.mkdir(parents=True, exist_ok=True)
    SENT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def frontmatter(path: pathlib.Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    try:
        meta = {}
        for line in raw.split("---", 2)[1].splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta
    except IndexError:
        return {}


def queue(limit: int) -> list:
    """Свежие статьи, которых нет в истории отправок."""
    done = sent_state()
    today = dt.date.today()
    items = []
    for path in sorted(POSTS.glob("*.md"), reverse=True):
        slug = path.stem
        if slug in done or SERVICE.search(slug):
            continue
        meta = frontmatter(path)
        if meta.get("status") == "draft" or meta.get("kind") in ("digest", "calendar"):
            continue
        if not (DOCS / (slug + ".html")).exists():
            continue
        stamp = meta.get("date", "")
        try:
            when = dt.date.fromisoformat(stamp[:10])
        except ValueError:
            continue
        if (today - when).days > 30:
            continue
        items.append((when, slug))
    items.sort(reverse=True)
    return items[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description="Переобход страниц в Яндексе")
    ap.add_argument("--limit", type=int, default=10, help="сколько адресов отправить")
    ap.add_argument("--only", nargs="*", help="конкретные слаги")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    c = conf()
    token = c.get("webmaster_token")
    uid, hid = c.get("user_id"), c.get("host_id")
    if not (token and uid and hid):
        raise SystemExit("в analytics.json нет user_id/host_id — перезапусти tools/yandex_auth.py")

    slugs = a.only or [s for _, s in queue(a.limit)]
    if not slugs:
        print("очередь пуста: всё свежее уже отправлено")
        return 0

    urls = ["%s/%s.html" % (SITE, s) for s in slugs]
    print("к отправке: %d" % len(urls))
    for u in urls:
        print("  " + u)
    if a.dry_run:
        return 0

    state = sent_state()
    ok = 0
    try:
        _, q = call(token, API % (uid, hid) + "/recrawl/quota")
        rest = q.get("quota_remainder")
        print("квота на сегодня: %s" % rest)
        if isinstance(rest, int) and rest < len(urls):
            urls = urls[:rest]
            print("обрезаю до квоты: %d" % len(urls))
    except Exception as exc:
        print("квоту не спросил: %s" % exc)

    failed = []
    for u in urls:
        slug = u.rsplit("/", 1)[-1][:-5]
        for attempt in (1, 2, 3):
            try:
                status, body = call(token, API % (uid, hid) + "/recrawl/queue",
                                    {"url": u}, method="POST")
                state[slug] = {"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                               "task": body.get("task_id"), "status": status}
                print("✓ %s" % slug)
                ok += 1
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    print("лимит исчерпан, останавливаюсь")
                    save_state(state)
                    return 0
                if attempt == 3:
                    failed.append((slug, "HTTP %s" % exc.code))
                else:
                    time.sleep(2 * attempt)
            except Exception as exc:
                if attempt == 3:
                    failed.append((slug, str(exc)[:80]))
                else:
                    time.sleep(2 * attempt)
        time.sleep(1)

    save_state(state)
    print("\nотправлено: %d" % ok)
    if failed:
        print("не пробилось (%d) — эти адреса отправь кнопкой в кабинете:" % len(failed))
        for slug, why in failed:
            print("  %s/%s.html  (%s)" % (SITE, slug, why))
        print("  кабинет: https://webmaster.yandex.ru/site/indexing/reindex/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
