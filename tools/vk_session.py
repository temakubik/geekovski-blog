#!/usr/bin/env python3
"""Сессия пользователя ВК из браузерного профиля — только для того, что не умеет
ключ сообщества.

Ключ сообщества не грузит фото в альбом сообщества (`photos.getWallUploadServer`
→ ошибка 27), не правит и не удаляет посты (`wall.edit` / `wall.delete` → 27).
Всё это умеет ключ доступа пользователя, который веб-клиент ВК держит в
localStorage профиля (`6287487:web_token:login:auth`). Здесь он читается через
CDP, кэшируется и обновляется — без ручных действий.

    python3 tools/vk_session.py            # показать состояние токена (обновить, если протух)
    python3 -c "import sys; sys.path.insert(0,'tools'); import vk_session; print(vk_session.token()[:8])"

Профиль браузера: ~/.hermes/profiles/geekovski/browser-profiles/vk
Порт CDP: 9337. Если браузер не запущен, поднимается headless-копия профиля,
забирает токен и закрывается — cookies остаются в профиле.
"""

import json
import os
import pathlib
import signal
import subprocess
import time
import urllib.request

PROFILE_DIR = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / "browser-profiles" / "vk"
CACHE = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".vk_web_token.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9337
LS_KEY = "6287487:web_token:login:auth"
FRESH_SECONDS = 600  # веб-токен живёт недолго, но живой сессии хватает на минуты


def _cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def _save(token: str):
    CACHE.write_text(json.dumps({"token": token, "ts": int(time.time())}), encoding="utf-8")
    CACHE.chmod(0o600)


def _cdp_alive(port=CDP_PORT) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=2):
            return True
    except Exception:
        return False


def _read_token_via_cdp(port=CDP_PORT) -> str:
    """Достать web_token из localStorage открытой вкладки vk.com."""
    import asyncio
    import websockets

    tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5))
    pages = [t for t in tabs if t.get("type") == "page" and "vk." in (t.get("url") or "")]
    if not pages:
        return ""
    expr = ("(() => { const raw = localStorage.getItem('%s');"
            " if (!raw) return ''; const j = JSON.parse(raw); return j.access_token || ''; })()" % LS_KEY)

    async def run():
        async with websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=8 * 1024 * 1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "returnByValue": True}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 1:
                    res = msg.get("result", {}).get("result", {})
                    return (res.get("value") or "").strip()

    return asyncio.run(run())


def _launch_headless(wait=40) -> str:
    """Поднять браузер на том же профиле, открыть vk.com, забрать токен и закрыть."""
    if _cdp_alive():
        return _read_token_via_cdp()
    if not PROFILE_DIR.exists():
        return ""
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--user-data-dir=%s" % PROFILE_DIR,
         "--remote-debugging-port=%d" % CDP_PORT, "--no-first-run",
         "--no-default-browser-check", "https://vk.com/feed"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + wait
    found = ""
    try:
        while time.time() < deadline and not found:
            if _cdp_alive():
                found = _read_token_via_cdp()
            time.sleep(2)
        return found
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()


def token(max_age=FRESH_SECONDS) -> str:
    """Свежий ключ пользователя. Пустая строка — если сессии нет."""
    cached = _cache()
    if cached.get("token") and time.time() - cached.get("ts", 0) < max_age:
        return cached["token"]
    if _cdp_alive():
        tok = _read_token_via_cdp()
        if tok:
            _save(tok)
            return tok
    token_file = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".vk_web_token"
    if token_file.exists():  # ручной кэш прошлых сессий
        tok = token_file.read_text(encoding="utf-8").strip()
        if tok:
            _save(tok)
            return tok
    tok = _launch_headless()
    if tok:
        _save(tok)
        return tok
    return ""


def upload_wall_photo(path, community_id: str, tok: str) -> str:
    """Загружает фото в альбом сообщества и возвращает строку для attachments.

    Ключ сообщества этого не умеет: фото уезжает в приватный альбом и к стене не
    цепляется. Работает только с сессией пользователя — поэтому токен берём
    выше, а не из VK_GROUP_TOKEN. Без access_key ВК выбрасывает фото из вложения.
    """
    import mimetypes
    import urllib.parse

    def call(method, params):
        req = urllib.request.Request(
            "https://api.vk.ru/method/" + method + "?v=5.199",
            data=urllib.parse.urlencode(params).encode(),
            headers={"Authorization": "Bearer " + tok,
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode())
        if "error" in payload:
            raise RuntimeError("%s: %s" % (method, payload["error"].get("error_msg")))
        return payload["response"]

    path = pathlib.Path(path)
    server = call("photos.getWallUploadServer", {"group_id": community_id})
    boundary = "----geekovski%d" % int(time.time())
    ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    body = ("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"%s\"\r\n"
            "Content-Type: %s\r\n\r\n" % (boundary, path.name, ctype)).encode()
    body += path.read_bytes() + ("\r\n--%s--\r\n" % boundary).encode()
    req = urllib.request.Request(server["upload_url"], data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=120) as r:
        up = json.loads(r.read().decode())
    if not up.get("photo"):
        raise RuntimeError("ВК вернул пустое фото (сбой загрузки), повтори")
    saved = call("photos.saveWallPhoto", {"group_id": community_id, "photo": up["photo"],
                                          "server": up["server"], "hash": up["hash"]})
    ph = saved[0]
    return "photo%s_%s_%s" % (ph["owner_id"], ph["id"], ph["access_key"])


if __name__ == "__main__":
    tok = token()
    if not tok:
        print("✗ сессии нет: войди в ВК в окне профиля", PROFILE_DIR)
        raise SystemExit(1)
    print("✓ токен пользователя есть, длина %d" % len(tok))
    try:
        import urllib.parse
        req = urllib.request.Request(
            "https://api.vk.ru/method/users.get?v=5.199",
            data=urllib.parse.urlencode({}).encode(),
            headers={"Authorization": "Bearer " + tok,
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            me = json.loads(r.read().decode()).get("response", [{}])[0]
            print("  вошёл как: %s %s (id %s)" % (me.get("first_name"), me.get("last_name"), me.get("id")))
    except Exception as e:
        print("  токен есть, но проверка не прошла:", e)
