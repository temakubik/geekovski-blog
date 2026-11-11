#!/usr/bin/env python3
"""Ищет одинаковые и почти одинаковые картинки в static/img блога.

Зачем: один и тот же пресс-кадр легко скачать дважды под разными именами
(`zelda-ocarina-switch-2.jpg` и `ocarina-of-time-reliz-96-switch.jpg`) и поставить
обложкой в две статьи. По именам файлов это не видно, глазу — видно сразу.

  python3 dup_images.py           # порог 12 (по умолчанию)
  python3 dup_images.py --max 6   # только почти идентичные

Сравнение — aHash: картинка приводится к 10×10 серому и сравнивается с медианой.
Пины, иконки, лого и favicon исключены: они все тёмные с текстом и дают ложные
пары между собой.
"""
import argparse
import itertools
import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
SKIP = ("-pin", "favicon", "icon", "logo", "og-default")


def ahash(path, size=10):
    im = Image.open(path).convert("L").resize((size, size), Image.LANCZOS)
    px = list(im.getdata())
    avg = sum(px) / len(px)
    return "".join("1" if v > avg else "0" for v in px)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=12, help="максимальное расстояние Хэмминга")
    ap.add_argument("--dir", default=str(IMG))
    a = ap.parse_args()

    folder = pathlib.Path(a.dir)
    files = [f for f in folder.iterdir()
             if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
             and not any(s in f.name for s in SKIP)]
    hashes = {}
    for f in files:
        try:
            hashes[f] = ahash(f)
        except Exception as e:  # битый файл не должен ронять отчёт
            print("! пропуск", f.name, str(e)[:60])

    pairs = []
    for x, y in itertools.combinations(hashes, 2):
        d = sum(1 for p, q in zip(hashes[x], hashes[y]) if p != q)
        if d <= a.max:
            pairs.append((d, x.name, y.name))
    pairs.sort()

    print("файлов:", len(hashes), "| близких пар:", len(pairs))
    for d, x, y in pairs:
        print(f"{d:>2}  {x}  <->  {y}")
    if not pairs:
        print("дублей нет")


if __name__ == "__main__":
    main()
