#!/usr/bin/env python3
"""Карточка поста для ВК 1080×1350 (4:5): фото + брендинг GEEKOVSKI.

    python3 tools/make_vk_post_card.py --img /tmp/raw.jpg --label "ИГРЫ" \
        --out content/vk/img/02-game-pass.jpg

Что накладывается: нижняя полоса с градиентом, логотип (белый вордмарк с синей
плиткой) слева, рубрика и адрес сайта моноширинным Medeo Mono справа, синяя
линия по нижнему краю. Ничего поверх кадра в его середине — фото остаётся
чистым, «водяной знак» живёт в полосе.

Размер 1080×1350 — максимальные пропорции 4:5, которые ВК показывает в ленте
целиком; фото обрезается по cover, а не растягивается.
"""

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONTS = ROOT / "static/fonts"
W, H = 1080, 1350

HTML = """<!doctype html><meta charset=utf-8>
<style>
  @font-face {{
    font-family: 'Medeo Mono';
    src: url("file://{fonts}/medeo-mono.woff2") format('woff2-variations');
    font-weight: 100 900;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:{w}px; height:{h}px; overflow:hidden; background:#0b0d11; }}
  .card {{ position:relative; width:{w}px; height:{h}px; overflow:hidden; }}
  .photo {{
    position:absolute; inset:0;
    background-image:url("file://{img}");
    background-size:cover;
    background-position:{pos};
    filter:saturate(.96) contrast(1.02);
  }}
  .veil {{
    position:absolute; inset:0;
    background:linear-gradient(to bottom,
      rgba(8,10,14,.30) 0%, rgba(8,10,14,0) 18%,
      rgba(8,10,14,0) 62%, rgba(8,10,14,.55) 84%, rgba(8,10,14,.94) 100%);
  }}
  .brand {{
    position:absolute; left:0; right:0; bottom:0;
    padding:0 56px 44px;
    display:flex; align-items:flex-end; justify-content:space-between; gap:24px;
  }}
  .brand img {{ display:block; height:{lh}px; width:auto; }}
  .meta {{
    font-family:'Medeo Mono', ui-monospace, monospace;
    font-weight:500; font-size:27px; line-height:1;
    letter-spacing:.16em; text-transform:uppercase;
    color:rgba(255,255,255,.78); white-space:nowrap;
    padding-bottom:6px;
  }}
  .meta b {{ color:#fff; font-weight:600; }}
  .rule {{ position:absolute; left:0; right:0; bottom:0; height:5px; background:#377BF0; }}
</style>
<div class="card">
  <div class="photo"></div>
  <div class="veil"></div>
  <div class="brand">
    <img src="file://{logo}">
    <div class="meta"><b>{label}</b> · GEEKOVSKI.RU</div>
  </div>
  <div class="rule"></div>
</div>
"""


def main():
    ap = argparse.ArgumentParser(description="Карточка поста ВК 1080×1350 с брендингом")
    ap.add_argument("--img", required=True, help="исходный кадр (jpg/png)")
    ap.add_argument("--label", required=True, help="рубрика: ИГРЫ, КИНО, ЖЕЛЕЗО…")
    ap.add_argument("--out", required=True, help="куда положить JPG")
    ap.add_argument("--logo-height", type=int, default=56, help="высота логотипа, px")
    ap.add_argument("--position", default="50% 42%", help="background-position фото")
    a = ap.parse_args()

    img = pathlib.Path(a.img).expanduser().resolve()
    if not img.exists():
        sys.exit(f"✗ нет файла: {img}")
    logo = (ROOT / "static/img/geekovski-logo.svg").resolve()

    work = ROOT / "tools/.vkpost"
    work.mkdir(exist_ok=True)
    page = work / "card.html"
    png = work / "card.png"
    page.write_text(
        HTML.format(w=W, h=H, img=img, logo=logo, fonts=FONTS,
                    lh=a.logo_height, label=a.label, pos=a.position),
        encoding="utf-8",
    )
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--user-data-dir=/tmp/ch_vkpost", "--hide-scrollbars",
         "--force-device-scale-factor=1", "--virtual-time-budget=8000",
         f"--window-size={W},{H}", f"--screenshot={png}", page.as_uri()],
        check=True, capture_output=True,
    )
    out = pathlib.Path(a.out).expanduser()
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "90",
                    str(png), "--out", str(out)], check=True, capture_output=True)
    print(f"→ {out} ({out.stat().st_size // 1024} КБ, {W}×{H})")


if __name__ == "__main__":
    main()
