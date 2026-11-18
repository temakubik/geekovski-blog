#!/usr/bin/env python3
"""Обложка сообщества ВК 1920×768: фото-фон + логотип GEEKOVSKI по центру.

    python3 tools/make_vk_cover.py --bg content/vk/img/vk-znakomstvo.jpg \
        --out content/vk/img/vk-oblozhka-1920x768.jpg

Размер — из справки ВК (vk.com/faq18266): рекомендуемый 1920×768, минимум
960×384, важное держать с отступом 10–15% от края. На телефоне виден центр
примерно 1196×400, поэтому логотип ставим в центральную зону.

Фон обрезается по формату обложки (object-fit: cover), а не растягивается.
Логотип — белый вордмарк с синей плиткой (`static/img/geekovski-logo.svg`):
на тёплом фото читается лучше тёмного и синего вариантов. Чтобы вордмарк не
тонул в деталях кадра, под ним радиальная тень, поверх — общий скрим.
"""

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 1920, 768

# Плотности затемнения: deep — по умолчанию, soft — если автору нужен видимый фон.
SCREMS = {
    "deep": dict(r0=".90", r1=".68", t0=".45", t1=".18", t2=".30", t3=".62"),
    "soft": dict(r0=".78", r1=".50", t0=".30", t1=".10", t2=".20", t3=".48"),
}

HTML = """<!doctype html><meta charset=utf-8>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:{w}px; height:{h}px; overflow:hidden; background:#0b0d11; }}
  .frame {{ position:relative; width:{w}px; height:{h}px; overflow:hidden; }}
  .bg {{
    position:absolute; inset:0;
    background-image:url("file://{bg}");
    background-size:cover;
    background-position:{pos};
    transform:scale({zoom});
    filter:saturate(.94) contrast(1.03);
  }}
  .scrim {{
    position:absolute; inset:0;
    background:
      radial-gradient(ellipse 58% 88% at 50% 50%, rgba(5,7,11,{r0}) 0%, rgba(5,7,11,{r1}) 46%, rgba(5,7,11,0) 80%),
      linear-gradient(to bottom, rgba(6,8,12,{t0}) 0%, rgba(6,8,12,{t1}) 38%, rgba(6,8,12,{t2}) 72%, rgba(6,8,12,{t3}) 100%);
  }}
  .logo {{
    position:absolute; left:50%; top:50%;
    transform:translate(-50%,-50%);
    width:{lw}px;
    filter:drop-shadow(0 10px 34px rgba(0,0,0,.55));
  }}
  .logo img {{ display:block; width:100%; }}
</style>
<div class="frame">
  <div class="bg"></div>
  <div class="scrim"></div>
  <div class="logo"><img src="file://{logo}"></div>
</div>
"""


def main():
    ap = argparse.ArgumentParser(description="Обложка сообщества ВК 1920×768")
    ap.add_argument("--bg", required=True, help="фон, путь от корня репозитория")
    ap.add_argument("--out", required=True, help="куда положить JPG")
    ap.add_argument("--logo-width", type=int, default=620, help="ширина логотипа, px (по умолчанию 620)")
    ap.add_argument("--position", default="50% 56%", help="background-position фона")
    ap.add_argument("--zoom", type=float, default=1.0, help="подзумить фон, чтобы убрать края кадра")
    ap.add_argument("--png", action="store_true", help="оставить и PNG рядом с JPG")
    ap.add_argument("--scrim", choices=["deep", "soft"], default="deep",
                    help="deep — вордмарк читается на любом кадре; soft — фон светлее, но контраст ниже")
    a = ap.parse_args()

    bg = (ROOT / a.bg).resolve()
    if not bg.exists():
        sys.exit(f"✗ нет файла фона: {bg}")
    logo = (ROOT / "static/img/geekovski-logo.svg").resolve()

    work = ROOT / "tools/.vkcover"
    work.mkdir(exist_ok=True)
    page = work / "cover.html"
    png = work / "cover.png"
    scrim = SCREMS[a.scrim]
    page.write_text(
        HTML.format(w=W, h=H, bg=bg, logo=logo, lw=a.logo_width, pos=a.position, zoom=a.zoom, **scrim),
        encoding="utf-8",
    )
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--user-data-dir=/tmp/ch_vkcover", "--hide-scrollbars",
         "--force-device-scale-factor=1", "--virtual-time-budget=8000",
         f"--window-size={W},{H}", f"--screenshot={png}", page.as_uri()],
        check=True, capture_output=True,
    )
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                    str(png), "--out", str(out)], check=True, capture_output=True)
    if a.png:
        subprocess.run(["cp", str(png), str(out.with_suffix(".png"))], check=True)
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"→ {shown} ({out.stat().st_size // 1024} КБ, {W}×{H})")


if __name__ == "__main__":
    main()