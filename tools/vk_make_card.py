#!/usr/bin/env python3
"""Карточка 16:9 для поста в ВК: обложка статьи + логотип, рубрика, домен.

    python3 tools/vk_make_card.py <slug> [--cover путь]
    → content/vk/img/<slug>-card.jpg

Формат и оформление — в tools/make_vk_post_card.py (16:9 по умолчанию).
"""
import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LABELS = {"xbox": "XBOX", "switch": "NINTENDO", "playstation": "PLAYSTATION",
          "pc": "PC-ИГРЫ", "vr": "VR", "gadgets": "ГАДЖЕТЫ", "kino": "КИНО",
          "serialy": "СЕРИАЛЫ", "ai": "AI"}
POSTS = ROOT / "content" / "posts"


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


def make_card(slug: str, cover=None) -> pathlib.Path:
    """Карточка 16:9 с логотипом из обложки статьи (tools/make_vk_post_card.py)."""
    meta = frontmatter(POSTS / ("%s.md" % slug))
    cover = (cover or meta.get("cover") or "").strip()
    if not cover:
        raise SystemExit("у статьи %s нет cover — карточку не из чего собрать" % slug)
    if cover.startswith("/Users/"):  # абсолютный путь — берём как есть
        img = pathlib.Path(cover)
    else:
        img = ROOT / "static" / cover.replace("/assets/", "", 1)
    out = ROOT / "content" / "vk" / "img" / ("%s-card.jpg" % slug)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_mtime >= img.stat().st_mtime:
        return out
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_vk_post_card.py"),
                    "--img", str(img), "--label", LABELS.get((meta.get("category") or "").strip(), "GEEKOVSKI"),
                    "--out", str(out)], check=True, capture_output=True, cwd=str(ROOT))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Карточка поста для ВК")
    ap.add_argument("slug", help="слаг статьи (имя файла без .md) или имя карточки")
    ap.add_argument("--cover", help="картинка вместо обложки статьи")
    a = ap.parse_args()
    out = make_card(a.slug, a.cover)
    print(out)
    print("  %d КБ" % (out.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
