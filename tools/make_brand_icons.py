#!/usr/bin/env python3
"""Иконки сайта из брендового набора (fav.svg + Simbol.svg).

Источник правды — бренд-папка: `fav.svg` (знак в скруглённом квадрате 32×32)
и `Simbol.svg` (тот же знак, 80×80). Оба уже лежат в static/img как
`favicon.svg` и `geekovski-icon.svg`.

Что делает скрипт:
  • favicon.svg — как есть (уже со скруглением 8.2/32);
  • favicon-32/48/96/120/192.png — прозрачный фон, скруглённые углы;
  • icon-512.png — то же в 512 (для разметки Organization.logo и PWA any);
  • apple-touch-icon.png и app-icon-512.png — полный квадрат #377BF0 без
    прозрачности: iOS и Android сами скругляют, а maskable-иконку Android
    режет по кругу, поэтому знак сидит в безопасной зоне (~66 %);
  • favicon.ico — многокадровый, самый крупный кадр 256.

  python3 tools/make_brand_icons.py
"""
import pathlib
import subprocess
import tempfile

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

BLUE = "#377BF0"
PNG_SIZES = [(32, "favicon-32.png"), (48, "favicon-48.png"), (96, "favicon-96.png"),
             (120, "favicon-120.png"), (192, "favicon-192.png"), (512, "icon-512.png")]
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _blank(path: pathlib.Path) -> bool:
    """Скриншот без рисунка (знак не успел отрисоваться) — один цвет на всё полотно."""
    im = Image.open(path).convert("RGB")
    return len(im.getcolors(maxcolors=1 << 16) or []) == 1


def shot(html: str, size: int, out: pathlib.Path, transparent: bool):
    """Chrome headless со своим профилем на каждый вызов — иначе два запуска
    подряд делят user-data-dir и второй отдаёт пустой кадр."""
    for attempt in range(3):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            tmp = f.name
        profile = tempfile.mkdtemp(prefix="ch-brandicons-")
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
               f"--user-data-dir={profile}", "--hide-scrollbars",
               "--force-device-scale-factor=1", "--virtual-time-budget=5000",
               f"--window-size={size},{size}",
               f"--screenshot={out}", f"file://{tmp}"]
        if transparent:
            cmd.insert(-1, "--default-background-color=00000000")
        subprocess.run(cmd, check=True, capture_output=True)
        if out.exists() and not _blank(out):
            return
        print("  повтор, кадр пустой:", out.name)
    raise SystemExit("не удалось отрисовать %s" % out.name)


def rounded(src: pathlib.Path, size: int, out: pathlib.Path):
    """Знак со скруглением — прозрачный фон."""
    shot("<!doctype html><html><head><meta charset='utf-8'><style>"
         "*{margin:0}html,body{background:transparent}"
         f"img{{width:{size}px;height:{size}px;display:block}}"
         f"</style></head><body><img src='{src.as_uri()}'></body></html>",
         size, out, transparent=True)


def fullbleed(src: pathlib.Path, size: int, out: pathlib.Path, art_ratio: float = 0.66):
    """Плашка #377BF0 во весь квадрат, знак по центру в безопасной зоне.

    Рисуем всегда в 512 и уменьшаем Pillow: в окне меньше ~200 px Chrome
    не отрисовывает <img> и отдаёт пустую плашку.
    """
    render = 512
    art = round(render * art_ratio)
    raw = out.with_name("_fullbleed_512.png")
    shot("<!doctype html><html><head><meta charset='utf-8'><style>"
         f"*{{margin:0}}html,body{{background:{BLUE}}}"
         "body{display:flex;align-items:center;justify-content:center}"
         f"img{{width:{art}px;height:{art}px;display:block}}"
         f"</style></head><body><img src='{src.as_uri()}'></body></html>",
         render, raw, transparent=False)
    im = Image.open(raw).convert("RGB")
    if size != render:
        im = im.resize((size, size), Image.Resampling.LANCZOS)
    im.save(out, "PNG")
    raw.unlink(missing_ok=True)


def main():
    fav = IMG / "favicon.svg"
    symbol = IMG / "geekovski-icon.svg"
    if not fav.exists() or not symbol.exists():
        raise SystemExit("нет favicon.svg / geekovski-icon.svg в static/img")

    for size, name in PNG_SIZES:
        rounded(fav, size, IMG / name)
        print("иконка", name)

    fullbleed(symbol, 180, IMG / "apple-touch-icon.png")
    print("apple-touch-icon.png")
    fullbleed(symbol, 512, IMG / "app-icon-512.png")
    print("app-icon-512.png")

    ico = Image.open(IMG / "icon-512.png").convert("RGBA")
    ico.save(IMG / "favicon.ico", sizes=ICO_SIZES)
    print("favicon.ico:", ", ".join("%dx%d" % s for s in ICO_SIZES))


if __name__ == "__main__":
    main()
