#!/usr/bin/env python3
"""Иконка установленного приложения: dark-плашка 512×512 с пиксельной «G»."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path("/tmp/appicon")
OUT.mkdir(exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://geekovski.ru/assets/fonts.css">
<style>
html,body{margin:0;width:512px;height:512px;overflow:hidden;background:#0A0C0F}
.wrap{width:512px;height:512px;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(circle at 50% 35%,#16202a 0%,#0A0C0F 70%);}
.g{font-family:'Chava',monospace;font-size:360px;line-height:1;color:#C9F24D;
   text-shadow:0 0 60px rgba(201,242,77,.35);}
</style></head><body><div class="wrap"><span class="g">G</span></div></body></html>"""

if __name__ == "__main__":
    page = OUT / "icon.html"
    page.write_text(HTML, encoding="utf-8")
    png = OUT / "icon-512.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--user-data-dir=/tmp/ch_appicon", "--hide-scrollbars",
                    "--virtual-time-budget=6000", "--window-size=512,512",
                    "--screenshot=%s" % png, page.as_uri()], check=True, capture_output=True)
    dst = ROOT / "static" / "img" / "app-icon-512.png"
    subprocess.run(["sips", "-z", "512", "512", str(png), "--out", str(dst)], check=True,
                   capture_output=True)
    print("app-icon-512.png", dst.stat().st_size // 1024, "КБ")
