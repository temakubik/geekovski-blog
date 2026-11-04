#!/usr/bin/env python3
"""Открыть вкладку в уже запущенном Chrome (CDP) и снять скриншот.

  python3 tools/cdp_shot.py --port 9224 --url "https://doop.design/c/x?page=y" \
      --out /tmp/shot.png --width 1440 --height 1200 --wait 8 --scroll 0
"""
import argparse
import asyncio
import base64
import json
import pathlib
import time
import urllib.parse
import urllib.request

import websockets


def new_tab(port, url):
    req = urllib.request.Request("http://127.0.0.1:%d/json/new?%s" % (port, urllib.parse.quote(url, safe="")),
                                method="PUT")
    return json.load(urllib.request.urlopen(req))


async def run(ws_url, out, width, height, wait, scroll):
    async with websockets.connect(ws_url, max_size=128 * 1024 * 1024) as ws:
        mid = 0

        async def cmd(method, **params):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == mid:
                    return msg.get("result", {})

        await cmd("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=1, mobile=False)
        await asyncio.sleep(wait)
        if scroll:
            await cmd("Runtime.evaluate", expression="window.scrollTo(0,%d)" % scroll)
            await asyncio.sleep(2)
        shot = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        pathlib.Path(out).write_bytes(base64.b64decode(shot["data"]))
        title = await cmd("Runtime.evaluate", expression="document.title", returnByValue=True)
        print("saved", out, pathlib.Path(out).stat().st_size, "|", title.get("result", {}).get("value"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9224)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", default="/tmp/cdp-shot.png")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1100)
    ap.add_argument("--wait", type=float, default=8)
    ap.add_argument("--scroll", type=int, default=0)
    a = ap.parse_args()
    tab = new_tab(a.port, a.url)
    asyncio.run(run(tab["webSocketDebuggerUrl"], a.out, a.width, a.height, a.wait, a.scroll))
