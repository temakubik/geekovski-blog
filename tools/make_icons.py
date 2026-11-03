#!/usr/bin/env python3
"""Собирает набор иконок сайта из пиксельного аватара (не из знака G).

Источник — static/img/geekovski-icon.svg (пиксельный портрет, 64×64).
Скрипт делает из него: favicon.svg со скруглёнными углами, favicon-32.png,
apple-touch-icon.png (180), icon-512.png и favicon.ico (16+32).

  python3 tools/make_icons.py
  python3 tools/make_icons.py --src static/img/logo.svg     # вернуть знак G
"""
import argparse
import pathlib
import re
import subprocess
import tempfile

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def rounded_svg(source: pathlib.Path, radius_ratio: float = 0.19) -> str:
    """Тот же рисунок, но в квадрате со скруглёнными углами — иначе в табе он смотрится кирпичом."""
    raw = source.read_text(encoding="utf-8")
    tag = re.search(r"<svg[^>]*>", raw)
    if not tag:
        raise SystemExit("в %s нет <svg>" % source)
    open_tag = tag.group(0)
    inner = raw[open_tag.__len__():].rsplit("</svg>", 1)[0]
    view = re.search(r'viewBox="([\d.\s]+)"', open_tag)
    vb = view.group(1).split() if view else ["0", "0", "100", "100"]
    w, h = float(vb[2]), float(vb[3])
    r = round(min(w, h) * radius_ratio, 2)
    head = ('<svg xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges" '
            f'width="800" height="800" viewBox="0 0 {w:g} {h:g}" role="img" aria-label="GEEKOVSKI">'
            f'<defs><clipPath id="r"><rect width="{w:g}" height="{h:g}" rx="{r}"/></clipPath></defs>'
            '<g clip-path="url(#r)">')
    return head + inner + "</g></svg>"


def rasterize(svg_path: pathlib.Path, size: int, out_path: str):
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>"
            "*{margin:0}html,body{background:transparent}"
            f"img{{width:{size}px;height:{size}px;display:block}}"
            f"</style></head><body><img src='file://{svg_path}'></body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--user-data-dir=/tmp/ch-icons", "--hide-scrollbars",
                    f"--window-size={size},{size}", "--default-background-color=00000000",
                    f"--screenshot={out_path}", f"file://{tmp}"],
                   check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(IMG / "geekovski-icon.svg"))
    a = ap.parse_args()
    src = pathlib.Path(a.src)
    if not src.exists():
        raise SystemExit("нет исходника: %s" % src)

    (IMG / "favicon.svg").write_text(rounded_svg(src), encoding="utf-8")
    print("favicon.svg из", src.name)

    for size, name in ((32, "favicon-32.png"), (180, "apple-touch-icon.png"), (512, "icon-512.png")):
        rasterize(IMG / "favicon.svg", size, str(IMG / name))
        print("иконка", name)

    ico = Image.open(IMG / "favicon-32.png").convert("RGBA")
    ico.save(IMG / "favicon.ico", sizes=[(16, 16), (32, 32)])
    print("favicon.ico")


if __name__ == "__main__":
    main()
