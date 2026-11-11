#!/usr/bin/env python3
"""Проверка повторяющихся картинок в статьях.

Зачем: агент регулярно ставил обложку ещё раз внутри текста, а иногда одну и ту
же фотографию — в две разные статьи. Глазами это ловится только на готовой
странице, поэтому проверка автоматическая.

Что проверяется:
  1. Одна и та же картинка дважды в одной статье (включая обложку).
  2. Одна и та же картинка в разных статьях (по имени файла и по md5).
  3. Визуально похожие кадры под разными именами — по перцептивному хешу.
  4. `cover:`/`pin:` и файлы в тексте, которых нет на диске.

  python3 tools/imgcheck.py               # все статьи, отчёт
  python3 tools/imgcheck.py --slug 2026-11-11-h3vr2-quest3
  python3 tools/imgcheck.py --fix         # убрать из текста повтор обложки
  python3 tools/imgcheck.py --strict      # код возврата 1 при найденных проблемах
"""
import argparse
import collections
import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSTS = ROOT / "content" / "posts"
IMG = ROOT / "static" / "img"

IMG_RE = re.compile(r"!\[[^\]]*\]\((/assets/img/[^)]+)\)")


def read_post(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^cover:\s*(/assets/img/\S+)", text, re.M)
    cover = m.group(1) if m else ""
    mp = re.search(r"^pin:\s*(/assets/img/\S+)", text, re.M)
    pin = mp.group(1) if mp else ""
    return text, cover, pin, IMG_RE.findall(text)


def local(url):
    return IMG / pathlib.Path(url).name


def md5(path):
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def signature(path, size=16):
    """Подпись кадра: сетка 16×16 в оттенках серого + средний цвет.

    Сравнение по средней абсолютной разнице (MAD) куда надёжнее, чем хеш
    «светлее/темнее среднего»: хеш считал похожими любые тёмные кадры со
    светлым пятном в центре, из-за чего отчёт тонул в ложных срабатываниях.
    Один и тот же кадр (даже кроп или пережатый) даёт MAD < 6, разные
    фотографии — обычно 20 и больше.
    """
    try:
        from PIL import Image
    except ImportError:
        return None, None
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None, None
    try:
        grey = list(im.convert("L").resize((size, size), Image.LANCZOS).getdata())
        small = im.resize((4, 4), Image.LANCZOS)
        rgb = list(small.getdata())
        col = tuple(sum(c[i] for c in rgb) / len(rgb) for i in range(3))
        return grey, col
    except Exception:
        return None, None


def mad(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def color_gap(a, b):
    return sum(abs(a[i] - b[i]) for i in range(3)) / 3


def scan(slug=None):
    posts = {}
    for f in sorted(POSTS.glob("*.md")):
        if slug and slug not in f.stem:
            continue
        text, cover, pin, body = read_post(f)
        posts[f.stem] = {"path": f, "text": text, "cover": cover,
                         "pin": pin, "body": body}
    return posts


def report(posts, fix=False, near=6):
    problems = 0
    seen = collections.defaultdict(set)          # файл → статьи
    hashes = {}

    for stem, p in posts.items():
        ordered = ([p["cover"]] if p["cover"] else []) + p["body"]
        counts = collections.Counter(x for x in ordered if x)

        # 1) повтор внутри статьи
        for url, n in counts.items():
            if n > 1:
                where = "обложка + текст" if url == p["cover"] else "несколько раз в тексте"
                print(f"[дубль] {stem}: {url.split('/')[-1]} ×{n} ({where})")
                problems += 1
                if fix and url == p["cover"]:
                    # убираем строку с обложкой из тела, оставляя саму обложку
                    lines = p["text"].splitlines()
                    kept, removed = [], 0
                    for line in lines:
                        if url in line and line.strip().startswith("!["):
                            removed += 1
                            continue
                        kept.append(line)
                    p["text"] = "\n".join(kept) + "\n"
                    p["path"].write_text(p["text"], encoding="utf-8")
                    print(f"        → строка с повтором обложки удалена")

        # 2) нет файла на диске
        for url in ordered:
            if url and not local(url).exists():
                print(f"[нет файла] {stem}: {url}")
                problems += 1

        for url in set(x for x in ordered if x):
            seen[url].add(stem)
            h = hashes.setdefault(url, signature(local(url)))

    # 3) одна картинка в разных статьях
    for url, stems in seen.items():
        if len(stems) > 1:
            print(f"[в разных статьях] {url.split('/')[-1]}: {', '.join(sorted(stems))}")
            problems += 1

    # 4) визуально похожие кадры
    names = [u for u in hashes if hashes[u][0] and local(u).exists()]
    pairs = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if local(a).name == local(b).name:
                continue
            ga, ca = hashes[a]
            gb, cb = hashes[b]
            if mad(ga, gb) <= near and color_gap(ca, cb) <= 12:
                print(f"[похожие] {local(a).name} ↔ {local(b).name} "
                      f"(MAD {mad(ga, gb):.1f})")
                pairs += 1
    if pairs:
        problems += pairs

    print()
    print("проблем:", problems)
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--near", type=float, default=4.0)
    a = ap.parse_args()
    posts = scan(a.slug)
    if not posts:
        print("статьи не найдены")
        return 0
    problems = report(posts, fix=a.fix, near=a.near)
    if a.strict and problems:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
