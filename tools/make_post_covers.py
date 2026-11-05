#!/usr/bin/env python3
"""Обложки постов по шаблону T6 канвы Doop: локальный рендер + (опционально) фрейм в архиве.

Зачем: кадр из Doop иногда лежит (таймаут рендера), а серия постов требует 1–3 обложек
за запуск. Тот же HTML шаблона T6 рендерится локальным Chrome'ом (шрифты тянутся с
geekovski.ru), файл кладётся в static/img/<slug>.jpg. С --push-frames в архив канвы
создаётся фрейм-источник (фото заранее загружается, Chava вшита data-URI).

Спека — JSON-массив:
  [{"slug": "amd-pk-padenie-2027", "kicker": "PC", "title": "ПК падает, AMD растёт",
    "date": "5 ноября 2026", "credit": "фото: Pexels / Atahan Demir",
    "photo": "/abs/path.jpg"   # или https://… (Pexels)
    "pos": "center 46%"}]

  python3 tools/make_post_covers.py --spec /tmp/covers.json
  python3 tools/make_post_covers.py --spec /tmp/covers.json --push-frames
"""
import argparse
import base64
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
TMP = pathlib.Path("/tmp/post-covers")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
T6 = "9bliZHjeHv"
CANVAS = "pY87uNTgj1"
PAGE = "pY87uNTgj1:covers"

sys.path.insert(0, str(ROOT / "tools"))
from doop_mcp import call  # noqa: E402


def t6_html():
    """HTML шаблона T6: сначала кэш в репозитории, иначе живой запрос в Doop.

    Кэш нужен, когда MCP-токен истёк (401) — обложки всё равно можно рендерить локально.
    """
    cache = ROOT / "tools" / "covers-t6.html"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    resp = call("get_frame", {"canvas_id": CANVAS, "frame_id": T6})
    html = json.loads(resp["result"]["content"][0]["text"])["html"]
    cache.write_text(html, encoding="utf-8")
    return html


def chava_face():
    b64 = base64.b64encode((ROOT / "static/fonts/Chava-Regular.ttf").read_bytes()).decode()
    return ("<style>@font-face{font-family:'Chava';src:url(data:font/ttf;base64,%s) "
            "format('truetype');font-weight:400;font-display:block}</style>" % b64)


def build_html(base, c, photo_src, embed_font=False):
    html = base
    html = html.replace(
        "<img class='photo' src='https://doop.design/a/ITfwviwnMs.jpg' alt=''>",
        "<img class='photo' src='%s' alt='' style='object-position:%s'>" % (photo_src, c.get("pos", "center 45%")))
    html = html.replace("<div class='kicker'>Nintendo Switch</div>", "<div class='kicker'>%s</div>" % c["kicker"])
    html = html.replace("<div class='h1'>Ocarina of Time выходит 5 ноября</div>", "<div class='h1'>%s</div>" % c["title"])
    html = html.replace("<span>2 ноября 2026</span>", "<span>%s</span>" % c["date"])
    html = html.replace("<span class='credit'>фото: Crisco 1492 / Wikimedia</span>",
                        "<span class='credit'>%s</span>" % c.get("credit", ""))
    if embed_font:
        html = html.replace("</head>", chava_face() + "</head>")
    return html


def upload(c):
    if not str(c["photo"]).startswith("http"):
        raise SystemExit("--push-frames ждёт URL фото: %s" % c["photo"])
    resp = call("upload_asset", {"canvas_id": CANVAS, "agent_name": "Hermes", "source_url": c["photo"]})
    return json.loads(resp["result"]["content"][0]["text"])["url"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--push-frames", action="store_true", help="создать фреймы в архиве канвы Doop")
    args = ap.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)
    base = t6_html()
    for c in json.loads(pathlib.Path(args.spec).read_text()):
        page = TMP / ("frame-%s.html" % c["slug"])
        page.write_text(build_html(base, c, "file://" + str(pathlib.Path(c["photo"]).expanduser()),
                                   embed_font=False))
        raw = TMP / ("raw-%s.png" % c["slug"])
        out = IMG / ("%s.jpg" % c["slug"])
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", "--window-size=1200,675",
                        "--virtual-time-budget=7000",
                        "--user-data-dir=/tmp/chrcov-%s" % c["slug"],
                        "--screenshot=%s" % raw, "file://%s" % page],
                       check=True, capture_output=True)
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82",
                        str(raw), "--out", str(out)], check=True, capture_output=True)
        subprocess.run(["sips", "-Z", "1600", str(out), "--out", str(out)],
                       check=True, capture_output=True)
        print("cover:", out, out.stat().st_size, "bytes")
        if args.push_frames:
            url = upload(c)
            resp = call("create_frame", {
                "canvas_id": CANVAS, "pageId": PAGE, "width": 1200, "height": 675,
                "name": c.get("frame_name") or ("Обложка · %s" % c["title"]),
                "html": build_html(base, c, url, embed_font=True), "agent_name": "Hermes",
            })
            txt = resp["result"]["content"][0]["text"]
            print("frame:", json.loads(txt)["frame"]["id"], json.loads(txt)["frame"]["name"])


if __name__ == "__main__":
    main()
