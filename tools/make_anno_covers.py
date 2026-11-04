#!/usr/bin/env python3
"""Обложки для календаря анонсов: шаблон T2 в Doop → локальный рендер → static/img/.

Doop-рендер сейчас отдаёт таймаут, поэтому кадр собирается тем же HTML и тем же
Chrome локально (шрифты берутся с geekovski.ru, как и у фрейма в канве).

  python3 tools/make_anno_covers.py             # все записи календаря без cover
  python3 tools/make_anno_covers.py --only gta  # одна по подстроке слага

Пишет файлы static/img/anno-<slug>.jpg и допечатывает cover: в content/posts/*-kalendar.md.
"""
import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = pathlib.Path("/tmp/anno-covers")

CAT_LABEL = {"switch": "Nintendo Switch", "playstation": "PlayStation", "xbox": "Xbox",
             "pc": "PC", "vr": "VR", "gadgets": "Гаджеты", "kino": "Кино",
             "serialy": "Сериалы", "ai": "AI"}
CAT_COLOR = {"switch": "#E60012", "playstation": "#2F6DF6", "xbox": "#2FB344",
             "pc": "#8B5CF6", "vr": "#A855F7", "gadgets": "#22D3EE",
             "kino": "#F0553F", "serialy": "#F5A524", "ai": "#14B8A6"}

HTML = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://geekovski.ru/assets/fonts.css">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1200px;height:675px;overflow:hidden;background:#0A0C0F;position:relative;
  font-family:'Chava',monospace;color:#E9EBEE}}
.bg{{position:absolute;inset:0;background:
  radial-gradient(circle at 78% 32%, {c}33 0%, transparent 58%),
  radial-gradient(circle at 20% 88%, {c}22 0%, transparent 55%),
  linear-gradient(160deg,#0f1319 0%,#0A0C0F 60%);}}
.grid{{position:absolute;inset:0;opacity:.20;
  background-image:linear-gradient(#1F252E 1px,transparent 1px),linear-gradient(90deg,#1F252E 1px,transparent 1px);
  background-size:60px 60px;}}
.scrim{{position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,#0A0C0F 100%);}}
.wrap{{position:absolute;inset:0;padding:56px 64px;display:flex;flex-direction:column;justify-content:space-between;z-index:2}}
.top{{display:flex;align-items:center;justify-content:space-between}}
.tag{{font-size:22px;letter-spacing:.22em;text-transform:uppercase;color:{c};border:2px solid {c};
  padding:6px 14px;border-radius:2px}}
.ep{{font-size:22px;letter-spacing:.22em;text-transform:uppercase;color:#8B939E}}
.bottom{{display:flex;flex-direction:column;gap:18px}}
.date{{font-size:34px;letter-spacing:.14em;text-transform:uppercase;color:#8B939E}}
.date b{{color:#C9F24D}}
h1{{font-size:{size}px;line-height:1.02;letter-spacing:-.01em;text-transform:uppercase;color:#E9EBEE;
  text-shadow:0 4px 30px rgba(0,0,0,.6)}}
.plat{{font-size:24px;letter-spacing:.18em;text-transform:uppercase;color:{c}}}
</style></head><body>
<div class="bg"></div><div class="grid"></div><div class="scrim"></div>
<div class="wrap">
  <div class="top"><span class="tag">{cat}</span><span class="ep">GEEKOVSKI</span></div>
  <div class="bottom">
    <div class="date"><b>{day}</b> {month} · {note}</div>
    <h1>{title}</h1>
    <div class="plat">{plat}</div>
  </div>
</div></body></html>"""

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
PLAT = {"switch2": "Switch 2", "switch": "Switch", "ps5": "PS5", "ps4": "PS4",
        "xbox": "Xbox Series", "pc": "PC", "mac": "Mac", "netflix": "Netflix",
        "kino": "Кино", "vr": "VR", "tv": "ТВ"}


def slugify(text):
    tr = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
          "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
          "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
          "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}
    s = "".join(tr.get(ch, ch) for ch in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50]


def records():
    """Записи календаря из content/posts/*-kalendar.md."""
    out = []
    for f in sorted((ROOT / "content" / "posts").glob("*kalendar*.md")):
        text = f.read_text(encoding="utf-8")
        cur = None
        for line in text.splitlines():
            s = line.strip()
            m = re.match(r"^-\s+category:\s*(\w+)", s)
            if m:
                cur = {"category": m.group(1), "file": f}
                out.append(cur)
                continue
            m = re.match(r"^(date|title|platforms|kind_note):\s*(.*)$", s)
            if m and cur is not None:
                cur[m.group(1)] = m.group(2).strip()
    return [r for r in out if r.get("title") and r.get("date")]


def render(rec):
    title = rec["title"]
    cat = rec["category"]
    color = CAT_COLOR.get(cat, "#C9F24D")
    y, m, d = rec["date"].split("-")
    size = 104 if len(title) <= 16 else (82 if len(title) <= 28 else 64)
    plats = " · ".join(PLAT.get(p, p.upper()) for p in rec.get("platforms", "").split())
    html = HTML.format(c=color, cat=CAT_LABEL.get(cat, cat.title()), title=title.upper(),
                       size=size, day=int(d), month=MONTHS[int(m) - 1].upper(),
                       note=(rec.get("kind_note") or "релиз").upper(), plat=plats)
    slug = slugify(title)
    OUT.mkdir(exist_ok=True)
    page = OUT / ("%s.html" % slug)
    page.write_text(html, encoding="utf-8")
    png = OUT / ("%s.png" % slug)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--user-data-dir=/tmp/ch_anno_%s" % slug[:8], "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--virtual-time-budget=6000",
                    "--window-size=1200,675", "--screenshot=%s" % png, page.as_uri()],
                   check=True, capture_output=True)
    jpg = IMG / ("anno-%s.jpg" % slug)
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82",
                    str(png), "--out", str(jpg)], check=True, capture_output=True)
    return slug, jpg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    IMG.mkdir(parents=True, exist_ok=True)
    made = []
    for rec in records():
        slug = slugify(rec["title"])
        if a.only and a.only not in slug:
            continue
        if (IMG / ("anno-%s.jpg" % slug)).exists():
            continue
        s, path = render(rec)
        made.append((s, path))
        print("cover:", s, path.stat().st_size, "b")
    print("итого:", len(made))


if __name__ == "__main__":
    main()
