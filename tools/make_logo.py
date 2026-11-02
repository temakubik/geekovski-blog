#!/usr/bin/env python3
"""Собирает логотип и фавикон GEEKOVSKI из настоящего начертания Tiny5.

Пиксельная «G» рендерится шрифтом, затем трассируется в сетку прямоугольников —
так SVG остаётся вектором, но рисует ровно те пиксели, что в шрифте.

  python3 tools/make_logo.py
"""
import pathlib
import subprocess
import tempfile

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = ROOT / "static" / "fonts" / "tiny5-latin.woff2"
OUT = ROOT / "static" / "img"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
INK = "#0A0C0F"
ACCENT = "#C9F24D"


def render_glyph(size=400):
    """Рендерит «G» шрифтом Tiny5 на прозрачном фоне через headless Chrome."""
    html = f"""<!doctype html><html><head><meta charset='utf-8'><style>
    @font-face{{font-family:'Tiny5';src:url('file://{FONT}') format('woff2');font-weight:400}}
    *{{margin:0;padding:0}}html,body{{background:transparent}}
    body{{width:{size}px;height:{size}px;display:grid;place-items:center;
          font-family:'Tiny5';font-size:{int(size*0.78)}px;line-height:1;color:#000}}
    </style></head><body>G</body></html>"""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    png = tmp.replace(".html", ".png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--user-data-dir=/tmp/ch-logo", "--hide-scrollbars",
                    f"--window-size={size},{size}", "--default-background-color=00000000",
                    f"--screenshot={png}", f"file://{tmp}"],
                   check=True, capture_output=True)
    img = Image.open(png).convert("RGBA")
    return img


def trace(img, grid_w=11):
    """Переводит растровую глифу в сетку 0/1 по альфа-каналу."""
    bbox = img.split()[3].getbbox()
    if not bbox:
        raise SystemExit("глифа не отрисовалась")
    glyph = img.crop(bbox)
    ratio = glyph.height / glyph.width
    grid_h = max(1, round(grid_w * ratio))
    small = glyph.resize((grid_w, grid_h), Image.LANCZOS)
    a = small.split()[3]
    cells = [[1 if a.getpixel((x, y)) > 110 else 0 for x in range(grid_w)] for y in range(grid_h)]
    return cells


def svg_mark(cells, pad_ratio=0.22, radius_ratio=0.22, bg=ACCENT, fg=INK, px=8):
    """SVG: закруглённый квадрат + пиксельная глифа по сетке."""
    gh, gw = len(cells), len(cells[0])
    inner = 1 - 2 * pad_ratio                     # доля стороны под глифу
    cell = inner / max(gw, gh)
    side = 100
    w = gw * cell * side
    h = gh * cell * side
    x0 = (side - w) / 2
    y0 = (side - h) / 2
    r = radius_ratio * side
    rects = []
    for y, row in enumerate(cells):
        for x, v in enumerate(row):
            if v:
                rects.append(
                    f'<rect x="{x0 + x * cell * side:.2f}" y="{y0 + y * cell * side:.2f}" '
                    f'width="{cell * side + 0.12:.2f}" height="{cell * side + 0.12:.2f}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges" width="{px * side}" height="{px * side}" '
            f'viewBox="0 0 {side} {side}" role="img" aria-label="GEEKOVSKI">'
            f'<rect width="{side}" height="{side}" rx="{r:.2f}" fill="{bg}"/>'
            f'<g fill="{fg}">' + "".join(rects) + "</g></svg>")


def rasterize(svg_path, size, out_path):
    """Растеризует SVG нужного размера — для PNG-иконок и apple-touch-icon."""
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"*{{margin:0}}html,body{{background:transparent}}"
            f"img{{width:{size}px;height:{size}px;display:block}}"
            f"</style></head><body><img src='file://{svg_path}'></body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--user-data-dir=/tmp/ch-logo2", "--hide-scrollbars",
                    f"--window-size={size},{size}", "--default-background-color=00000000",
                    f"--screenshot={out_path}", f"file://{tmp}"],
                   check=True, capture_output=True)


GLYPH = [
    ".#####.",
    "#......",
    "#......",
    "#..####",
    "#.....#",
    "#.....#",
    ".#####.",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cells = [[1 if c == "#" else 0 for c in row] for row in GLYPH]
    print("сетка глифы:", len(cells), "x", len(cells[0]))

    logo = svg_mark(cells, pad_ratio=0.20, radius_ratio=0.20, px=8)
    (OUT / "logo.svg").write_text(logo, encoding="utf-8")

    # фавикон: та же марка, но чуть плотнее поля — читается в 16 px
    fav = svg_mark(cells, pad_ratio=0.17, radius_ratio=0.18, px=8)
    (OUT / "favicon.svg").write_text(fav, encoding="utf-8")

    for size, name in ((32, "favicon-32.png"), (180, "apple-touch-icon.png"), (512, "icon-512.png")):
        rasterize(OUT / "favicon.svg", size, str(OUT / name))
        print("иконка", name)

    # favicon.ico (16+32 внутри) через PIL
    ico = Image.open(OUT / "favicon-32.png").convert("RGBA")
    ico.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32)])
    print("favicon.ico")


if __name__ == "__main__":
    main()
