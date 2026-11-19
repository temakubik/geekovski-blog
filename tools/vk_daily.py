#!/usr/bin/env python3
"""Расклад постов в ВК: три отложки в день из свежих статей блога.

    python3 tools/vk_daily.py            # показать, что уйдёт и когда (ничего не ставит)
    python3 tools/vk_daily.py --apply    # поставить отложенные записи в ВК

Логика: берём статьи блога, которых ещё нет в content/vk/posted.json, самые
свежие — вперёд, и раскладываем по трём слотам. Дубли отсекает posted.json.

Картинка обязательна: ссылка вложением не работает (`link_photo_sizing_rule`),
поэтому пост идёт фото-вложением (карточка 16:9 с логотипом) + URL строкой.
Фото грузится сессией пользователя из браузерного профиля `vk` — ключ
сообщества этого не умеет.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
STATE = ROOT / "content" / "vk" / "posted.json"
PUBLISH = ROOT / "tools" / "vk_publish.py"
SLOTS = ("09:30", "13:30", "19:30")


def busy_slots(gid: str) -> list:
    """Отложки, которые уже стоят в ВК: их время (unix) — чтобы не занять слот дважды."""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import vk_session
        import urllib.parse
        import urllib.request
        tok = vk_session.token()
        if not tok:
            return []
        body = urllib.parse.urlencode({"owner_id": "-" + gid, "filter": "postponed",
                                       "count": 20, "v": "5.199"}).encode()
        req = urllib.request.Request("https://api.vk.ru/method/wall.get", data=body,
                                     headers={"Authorization": "Bearer " + tok,
                                              "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
        return [it["date"] for it in payload.get("response", {}).get("items", [])]
    except Exception:
        return []



def make_card(slug: str) -> pathlib.Path:
    """Карточка 16:9 с логотипом из обложки статьи (tools/make_vk_post_card.py)."""
    meta = frontmatter(POSTS / ("%s.md" % slug))
    cover = (meta.get("cover") or "").strip()
    if not cover:
        raise SystemExit("у статьи %s нет cover — карточку не из чего собрать" % slug)
    if cover.startswith("/Users/"):
        img = pathlib.Path(cover)
    else:
        img = ROOT / "static" / cover.replace("/assets/", "", 1)
    out = ROOT / "content" / "vk" / "img" / ("%s-card.jpg" % slug)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_mtime >= img.stat().st_mtime:
        return out
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_vk_post_card.py"),
                    "--img", str(img), "--label", (meta.get("category") or "GEEKOVSKI").upper(),
                    "--out", str(out)], check=True, capture_output=True, cwd=str(ROOT))
    return out


def frontmatter(path: pathlib.Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    meta = {}
    if raw.startswith("---"):
        try:
            _, fm, _ = raw.split("---", 2)
        except ValueError:
            return meta
        for line in fm.strip().splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def candidates(posted: dict, days: int = 3) -> list:
    """Свежие статьи без дублей. Окно по дате: старые материалы в ВК не тащим —
    там они выглядят как новости двухнедельной давности."""
    items = []
    for path in POSTS.glob("*.md"):
        meta = frontmatter(path)
        slug = meta.get("slug") or path.stem
        if slug in posted:
            continue
        if meta.get("status") == "draft":
            continue
        # дайджесты и календарь — не отдельные материалы: в ВК им нечего сказать
        if meta.get("kind") in ("digest", "calendar"):
            continue
        stamp = meta.get("date", "")
        try:
            when = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
        except ValueError:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", path.stem)
            if not m:
                continue
            when = datetime.strptime(m.group(1), "%Y-%m-%d")
        if when < datetime.now() - timedelta(days=days):
            continue
        items.append((when, slug, meta.get("title", slug)))
    items.sort(reverse=True)
    return items


def main() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import vk_smm
        vk_smm.load_profile_env()  # в кроне окружение пустое, ключи лежат в профиле
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Три отложки в ВК на день")
    ap.add_argument("--apply", action="store_true", help="реально поставить в ВК")
    ap.add_argument("--date", help="день раскладки, YYYY-MM-DD (по умолчанию сегодня)")
    ap.add_argument("--slots", default=",".join(SLOTS), help='слоты через запятую, "09:30,13:30,19:30"')
    ap.add_argument("--per-day", type=int, default=3, help="сколько постов в день")
    ap.add_argument("--days", type=int, default=3, help="окно свежести статей, дней")
    args = ap.parse_args()

    day = args.date or datetime.now().strftime("%Y-%m-%d")
    slots = [s.strip() for s in args.slots.split(",") if s.strip()][: args.per_day]
    posted = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

    picks = candidates(posted, args.days)[: len(slots)]
    if not picks:
        print("нечего ставить: все свежие статьи уже в ВК")
        return 0

    gid = (os.environ.get("VK_GROUP_ID") or "").strip()
    taken = busy_slots(gid) if args.apply and gid else []

    now = datetime.now()
    for slot, (when, slug, title) in zip(slots, picks):
        run_at = datetime.strptime("%s %s" % (day, slot), "%Y-%m-%d %H:%M")
        late = run_at < now + timedelta(minutes=10)
        stamp = run_at.timestamp()
        busy = any(abs(stamp - t) < 3600 for t in taken)
        note = "  (слот уже прошёл, пропускаю)" if late else ("  (слот занят отложкой, пропускаю)" if busy else "")
        print("%s — %s%s" % (slot, title[:70], note))
        print("         %s" % slug)
        if not args.apply or late or busy:
            continue
        try:
            card = make_card(slug)
        except SystemExit as exc:
            print("         ✗ " + str(exc))
            continue
        res = subprocess.run(
            [sys.executable, str(PUBLISH), "--slug", slug, "--photo", str(card),
             "--publish-at", run_at.strftime("%Y-%m-%d %H:%M"), "--post"],
            capture_output=True, text=True, cwd=str(ROOT))
        tail = ((res.stdout or "").strip().splitlines() or [""])[-1]
        if res.returncode != 0:
            print("         ✗ " + ((res.stderr or res.stdout).strip().splitlines() or ["ошибка"])[-1])
        else:
            print("         " + tail)

    skipped = len(candidates(posted, args.days)) - len(picks)
    if skipped > 0:
        print("\nв остатке на следующие дни: %d статей" % skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
