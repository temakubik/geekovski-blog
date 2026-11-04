import pathlib, subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path("/Users/user/Projects/geekovski-blog")
SHOTS = ROOT / "preview" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def shot(url, out, height=3000, width=1240):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--user-data-dir=/tmp/ch_sgfull", "--hide-scrollbars",
                    "--virtual-time-budget=7000", f"--window-size={width},{height}",
                    f"--screenshot={out}", url], check=True, capture_output=True)


def label(img, pad=16):
    """Тёмная подложка под каждой полосой, чтобы швы между кусками были видны."""
    w, h = img.size
    out = Image.new("RGB", (w + pad * 2, h + pad * 2), (10, 12, 15))
    out.paste(img, (pad, pad))
    return out


def main():
    full = "/tmp/sg-full.png"
    shot("http://127.0.0.1:8791/style-guide.html", full, height=4200)
    im = Image.open(full).convert("RGB")
    # режем длинную страницу на три читаемых полосы
    cuts = [(0, 1400), (1300, 2700), (2600, 4000)]
    parts = []
    for top, bottom in cuts:
        band = im.crop((0, top, im.width, min(bottom, im.height)))
        band.thumbnail((880, 10000), Image.LANCZOS)
        parts.append(label(band))
    gap = 18
    W = max(p.width for p in parts)
    H = sum(p.height for p in parts) + gap * (len(parts) - 1)
    sheet = Image.new("RGB", (W, H), (10, 12, 15))
    y = 0
    for p in parts:
        sheet.paste(p, ((W - p.width) // 2, y))
        y += p.height + gap
    sheet.save(SHOTS / "styleguide-full.png")
    print("styleguide-full.png", sheet.size)


if __name__ == "__main__":
    main()
