#!/usr/bin/env python3
"""Картинка для соцсетей: tools/og-source.html → static/img/og-default.png (1200×630).

Страница ссылается на /assets/…, поэтому ей нужен корень с ассетами: поднимаем
локальный http.server на временном каталоге, где assets — симлинки на static,
и снимаем скриншот headless-Chrome.

  python3 tools/make_og.py
"""
import http.server
import pathlib
import socketserver
import subprocess
import tempfile
import threading

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
OUT = STATIC / "img" / "og-default.png"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 1200, 630


def main():
    srv_root = pathlib.Path(tempfile.mkdtemp(prefix="og-"))
    assets = srv_root / "assets"
    assets.mkdir()
    (assets / "fonts.css").symlink_to(STATIC / "fonts.css")
    (assets / "fonts").symlink_to(STATIC / "fonts")
    (assets / "img").symlink_to(STATIC / "img")
    (srv_root / "og.html").write_text((ROOT / "tools" / "og-source.html").read_text(encoding="utf-8"),
                                      encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(srv_root), **k)

        def log_message(self, format, *args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Quiet) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        raw = srv_root / "og.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                        f"--user-data-dir={srv_root / 'profile'}", "--hide-scrollbars",
                        "--force-device-scale-factor=1", "--virtual-time-budget=6000",
                        f"--window-size={W},{H}", f"--screenshot={raw}",
                        f"http://127.0.0.1:{port}/og.html"], check=True, capture_output=True)
        httpd.shutdown()

    im = Image.open(raw).convert("RGB")
    if im.size != (W, H):
        raise SystemExit("кадр не %dx%d, а %s" % (W, H, im.size))
    im.save(OUT, "PNG", optimize=True)
    print("og-default.png", OUT.stat().st_size // 1024, "КБ")


if __name__ == "__main__":
    main()
