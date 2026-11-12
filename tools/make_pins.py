#!/usr/bin/env python3
"""Вертикальные пины 1000×1500 для Pinterest: шаблон T7 из канвы GEEKOVSKI.

Зачем: в ленте Pinterest горизонтальная обложка 16:9 выглядит полоской и обрезается,
поэтому у каждой статьи должен быть отдельный файл 2:3, ссылка на который уходит
в share-ссылку через `media=`.

  python3 tools/make_pins.py              # все статьи без pin
  python3 tools/make_pins.py --force      # пересобрать все
  python3 tools/make_pins.py --only gta   # по подстроке слага

Пишет static/img/<slug>-pin.jpg и вписывает строку `pin:` в content/posts/<slug>.md.
"""
import argparse
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
OUT = pathlib.Path("/tmp/pins")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CAT_LABEL = {"switch": "Nintendo Switch", "playstation": "PlayStation", "xbox": "Xbox",
             "pc": "PC-игры", "vr": "VR", "gadgets": "Гаджеты", "kino": "Кино",
             "serialy": "Сериалы", "ai": "AI"}
CAT_COLOR = {"switch": "#E60012", "playstation": "#2F6DF6", "xbox": "#2FB344",
             "pc": "#8B5CF6", "vr": "#A855F7", "gadgets": "#22D3EE",
             "kino": "#F0553F", "serialy": "#F5A524", "ai": "#14B8A6"}

HTML = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://geekovski.ru/assets/fonts.css">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1000px;height:1500px;overflow:hidden;background:#0A0C0F;position:relative;
  font-family:'Medeo Sans',sans-serif;color:#E9EBEE}}
.photo{{position:absolute;inset:0;background-image:url('{img}');background-size:cover;background-position:center top}}
.scrim{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(10,12,15,.15) 0%,rgba(10,12,15,.55) 45%,rgba(10,12,15,.97) 78%);}}
.tint{{position:absolute;inset:0;background:radial-gradient(circle at 80% 10%,{c}33 0%,transparent 55%);mix-blend-mode:screen}}
.wrap{{position:absolute;inset:0;padding:56px 60px 64px;display:flex;flex-direction:column;justify-content:space-between;z-index:2}}
.top{{display:flex;align-items:center;justify-content:space-between}}
.brand{{font-family:'Chava',monospace;font-size:26px;letter-spacing:.22em;color:#7FA8F7}}
.tag{{font-family:'Chava',monospace;font-size:24px;letter-spacing:.16em;color:{c};border:2px solid {c};padding:6px 14px}}
.bottom{{display:flex;flex-direction:column;gap:22px}}
h1{{font-family:'RGS';font-style:italic;font-weight:900;font-size:{size}px;line-height:1.02;letter-spacing:-.025em}}
.meta{{font-family:'Chava',monospace;font-size:24px;letter-spacing:.14em;text-transform:uppercase;color:#8B939E}}
.meta b{{color:#7FA8F7}}
</style></head><body>
<div class="photo"></div><div class="tint"></div><div class="scrim"></div>
<div class="wrap">
  <div class="top"><span class="brand">GEEKOVSKI</span><span class="tag">{cat}</span></div>
  <div class="bottom">
    <h1>{title}</h1>
    <div class="meta"><b>{day} {month}</b> · {cat} · geekovski.ru</div>
  </div>
</div></body></html>"""

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def read_meta(path):
    text = path.read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, text


def abspath(url):
    return "https://geekovski.ru" + url if url.startswith("/") else url


def photo_url(cover):
    """Картинку подставляем data-URI из local-файла.

    Пин рендерится по file://, и внешний URL в background-image там не грузится
    (или грузится уже после снимка) — получается чёрная плашка. Локальный файл
    в base64 снимает и сеть, и гонку с загрузкой.
    """
    import base64, mimetypes
    url = abspath(cover)
    if url.startswith("http://") or url.startswith("https://"):
        if url.startswith("https://geekovski.ru"):
            # cover: пишется как /assets/img/x.jpg, а файл лежит в static/img/x.jpg —
            # префикс /assets/ надо снять, иначе путь ведёт в несуществующий static/assets
            rel = url.split("geekovski.ru", 1)[1].lstrip("/")
            if rel.startswith("assets/"):
                rel = rel[len("assets/"):]
            local = ROOT / "static" / rel
            if local.exists():
                mime = mimetypes.guess_type(str(local))[0] or "image/jpeg"
                return "data:%s;base64,%s" % (mime, base64.b64encode(local.read_bytes()).decode())
        return url
    return url


def render(slug, meta):
    cat = meta.get("category", "ai")
    color = CAT_COLOR.get(cat, "#7FA8F7")
    title = meta.get("title", "").strip().rstrip(".")
    size = 92 if len(title) <= 40 else (76 if len(title) <= 60 else 62)
    day, month = "", ""
    stem = re.match(r"(\d{4})-(\d{2})-(\d{2})", slug)
    date = meta.get("date", "")
    dm = re.match(r"(\d{4})-(\d{2})-(\d{2})", date)
    if dm:
        day, month = str(int(dm.group(3))), MONTHS[int(dm.group(2)) - 1]
    elif stem:
        day, month = str(int(stem.group(3))), MONTHS[int(stem.group(2)) - 1]
    html = HTML.format(img=photo_url(meta.get("cover", "")), c=color, cat=CAT_LABEL.get(cat, cat),
                       title=title, size=size, day=day, month=month)
    OUT.mkdir(exist_ok=True)
    page = OUT / ("%s.html" % slug)
    page.write_text(html, encoding="utf-8")
    png = OUT / ("%s.png" % slug)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--allow-file-access-from-files",
                    "--user-data-dir=/tmp/ch_pin_%s" % slug[:10], "--hide-scrollbars",
                    "--virtual-time-budget=7000", "--window-size=1000,1500",
                    "--screenshot=%s" % png, page.as_uri()], check=True, capture_output=True)
    jpg = IMG / ("%s-pin.jpg" % slug)
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82",
                    str(png), "--out", str(jpg)], check=True, capture_output=True)
    return jpg


def write_pin(path, text, slug):
    line = "pin: /assets/img/%s-pin.jpg" % slug
    if re.search(r"^pin:", text, re.M):
        text = re.sub(r"^pin:.*$", line, text, count=1, flags=re.M)
    else:
        # вставляем сразу после cover:, чтобы блок читался логично
        if re.search(r"^cover:", text, re.M):
            text = re.sub(r"^(cover:.*)$", r"\1\n" + line, text, count=1, flags=re.M)
        else:
            text = text.replace("---\n\n", "---\n", 1)
            text = re.sub(r"^\n---\n", "\n---\n" + line + "\n", text, count=1)
    path.write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    IMG.mkdir(parents=True, exist_ok=True)
    made = 0
    for f in sorted((ROOT / "content" / "posts").glob("*.md")):
        slug = f.stem
        if a.only and a.only not in slug:
            continue
        meta, text = read_meta(f)
        if meta.get("kind") in ("digest", "calendar"):
            continue
        if not meta.get("cover"):
            print("нет cover, пропуск:", slug)
            continue
        target = IMG / ("%s-pin.jpg" % slug)
        if target.exists() and not a.force:
            if not meta.get("pin"):
                write_pin(f, text, slug)
            continue
        jpg = render(slug, meta)
        write_pin(f, text, slug)
        made += 1
        print("pin:", slug, jpg.stat().st_size // 1024, "КБ")
    print("сделано:", made)


if __name__ == "__main__":
    main()
