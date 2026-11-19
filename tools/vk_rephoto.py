#!/usr/bin/env python3
"""Пересобрать карточку поста в 16:9 и заменить вложение у уже вышедших/отложенных записей.

    python3 tools/vk_rephoto.py                 # только показать, что будет
    python3 tools/vk_rephoto.py --apply         # пересобрать и заменить в ВК
    python3 tools/vk_rephoto.py --apply --slug <slug>

Зачем: обложки статей прямоугольные, и в 4:5 ВК обрезает бока. Здесь карточка
собирается в 16:9, заливается в альбом сообщества, а пост получает новое
вложение через wall.edit (ключ сообщества этого не умеет — нужна сессия
пользователя, tools/vk_session.py).

ВАЖНО: wall.edit по отложенной записи публикует её сразу — ВК сбрасывает
publish_date. Поэтому отложенные посты этот скрипт не трогает: их надо
удалить и поставить заново с новой карточкой и тем же временем.
"""

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import vk_publish  # noqa: E402
import vk_smm  # noqa: E402
import vk_session  # noqa: E402

POSTS = ROOT / "content" / "posts"
STATE = ROOT / "content" / "vk" / "posted.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Заменить карточку в постах на 16:9")
    ap.add_argument("--apply", action="store_true", help="реально заменить вложения в ВК")
    ap.add_argument("--slug", help="только один пост")
    a = ap.parse_args()

    vk_smm.load_profile_env()
    gid = vk_smm.group_id()
    state = json.loads(STATE.read_text(encoding="utf-8"))
    token = vk_session.token() if a.apply else ""
    if a.apply and not token:
        vk_smm.die("нет сессии пользователя ВК: войди в профиль browser-profiles/vk")

    postponed = set()
    if a.apply:
        pp = vk_publish.api("wall.get", {"owner_id": "-" + gid, "filter": "postponed",
                                         "count": 50}, token)
        postponed = {it["id"] for it in pp.get("response", {}).get("items", [])}

    for slug, info in state.items():
        if a.slug and slug != a.slug:
            continue
        path = POSTS / f"{slug}.md"
        if not path.exists():
            print(f"— {slug}: нет статьи, пропускаю")
            continue
        meta = vk_publish.parse_frontmatter(path)
        raw = meta.get("cover") or meta.get("pin")
        if not raw:
            print(f"— {slug}: нет cover/pin в статье, пропускаю")
            continue
        img = vk_publish.resolve_image(raw)
        card = vk_publish.make_card(img, meta.get("category", ""),
                                    vk_publish.CARDS / f"{slug}-16x9.jpg")
        print(f"— {slug}: карточка {card.name} ({card.stat().st_size // 1024} КБ)")
        if not a.apply:
            continue
        if info["post_id"] in postponed:
            print(f"   ⏸ пост {info['post_id']} ещё в отложенных: правка опубликовала бы его "
                  f"сейчас. Удали его в ВК и поставь заново с --publish-at.")
            continue
        attach = vk_publish.upload_photo(card, gid)["attach"]
        payload = vk_publish.api("wall.edit", {
            "owner_id": "-" + gid,
            "post_id": info["post_id"],
            "message": info.get("text", ""),
            "attachments": attach,
        }, token)
        if "error" in payload:
            print(f"   ✗ правка поста {info['post_id']}: {vk_publish.explain_error(payload['error'])}")
        else:
            print(f"   ✓ пост {info['post_id']} получил новое фото {attach}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
