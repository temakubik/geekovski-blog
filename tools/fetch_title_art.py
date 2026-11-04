#!/usr/bin/env python3
"""Картинки для календаря и базы тайтлов: официальные пресс-кадры издателей.

Источник — страницы пресс-центров и магазинов (Rockstar, Nintendo, Blizzard
gamespress, Steam, PlayStation Store). Скачиваем в static/img/, пишем в запись
поля cover/image/credit (издатель + страница, откуда взят кадр).

  python3 tools/fetch_title_art.py --set gta-6="https://..." --name gta-6

Скрипт не угадывает файлы: адрес кадра передаётся явно, чтобы в базу не попал
случайный баннер вместо ключевого арта.
"""
import argparse
import pathlib
import subprocess
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36"}


def grab(url, name, width=1600):
    IMG.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
    raw = IMG / ("%s-raw%s" % (name, ext))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw.write_bytes(r.read())
    jpg = IMG / ("%s.jpg" % name)
    # WebP/PNG → JPEG 1600 px по ширине, 16:9-кроп по центру
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "84", str(raw), "--out", str(jpg)],
                   check=True, capture_output=True)
    w = int(subprocess.run(["sips", "-g", "pixelWidth", str(jpg)], capture_output=True, text=True)
            .stdout.strip().split()[-1])
    h = int(subprocess.run(["sips", "-g", "pixelHeight", str(jpg)], capture_output=True, text=True)
            .stdout.strip().split()[-1])
    target_h = int(w * 9 / 16)
    if h > target_h:
        subprocess.run(["sips", "-c", str(target_h), str(w), str(jpg)], check=True, capture_output=True)
    elif h < target_h:
        target_h = h
    raw.unlink(missing_ok=True)
    size = jpg.stat().st_size
    print("img: %s.jpg %d×%d %d КБ" % (name, w, target_h, size // 1024))
    return jpg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], help='name="url"')
    a = ap.parse_args()
    for pair in a.set:
        name, url = pair.split("=", 1)
        grab(url.strip('"'), name)
