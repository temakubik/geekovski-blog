import sys
from PIL import Image, ImageEnhance

src, dst = sys.argv[1], sys.argv[2]
bright = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
sat = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

im = Image.open(src).convert("RGB")
w, h = im.size
# центральный кроп 16:9
target = 16 / 9
if w / h > target:
    nw = int(h * target)
    im = im.crop(((w - nw) // 2, 0, (w + nw) // 2, h))
else:
    nh = int(w / target)
    im = im.crop((0, (h - nh) // 2, w, (h + nh) // 2))
im = im.resize((2400, 1350), Image.LANCZOS)
if bright != 1.0:
    im = ImageEnhance.Brightness(im).enhance(bright)
if sat != 1.0:
    im = ImageEnhance.Color(im).enhance(sat)
im.save(dst, quality=90)
print(dst, im.size)
