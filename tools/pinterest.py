#!/usr/bin/env python3
"""Публикатор Pinterest: OAuth, токены, пины из статей GEEKOVSKI.

    python3 tools/pinterest.py auth-url            # ссылка на согласие
    python3 tools/pinterest.py exchange --code …   # обмен кода на токены
    python3 tools/pinterest.py check               # кто мы и какие доски видим
    python3 tools/pinterest.py boards              # список досок
    python3 tools/pinterest.py pin --slug 2026-11-24-2100-tarkov-unity-6 --board <id>
    python3 tools/pinterest.py bulk --board <id> --limit 10   # пачка по свежим статьям

Ключи приложения — в .env профиля: PINTEREST_APP_ID, PINTEREST_APP_SECRET.
Токены (access + refresh) — в ~/.hermes/profiles/geekovski/.pinterest_token.json,
права 600. Access живёт ~30 дней, refresh ~1 год; `token()` сам обновляет.

ВАЖНО про доступ: приложение стартует в Trial — созданные пины видны только
создателю (sandbox). Чтобы пины уходили в ленту людям, нужно Standard access:
видео-демо работы через OAuth и ревью. До апгрейда скрипт работает, но смысла
публиковать пачками нет.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
IMG = ROOT / "static" / "img"
STATE = ROOT / "content" / "pinterest" / "posted.json"
TOKEN_FILE = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".pinterest_token.json"
API = "https://api.pinterest.com/v5"
REDIRECT = "http://localhost:8787/callback"
SCOPES = ["pins:read", "pins:write", "boards:read", "boards:write", "user_accounts:read"]


def load_env() -> None:
    env_path = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def die(msg: str) -> NoReturn:
    sys.stderr.write("✗ %s\n" % msg)
    raise SystemExit(1)


def app() -> tuple[str, str]:
    load_env()
    cid = os.environ.get("PINTEREST_APP_ID", "")
    sec = os.environ.get("PINTEREST_APP_SECRET", "")
    if not cid or not sec:
        die("нет PINTEREST_APP_ID / PINTEREST_APP_SECRET в .env профиля")
    return cid, sec


def _basic() -> str:
    cid, sec = app()
    return "Basic " + base64.b64encode(("%s:%s" % (cid, sec)).encode()).decode()


def _save_token(payload: dict) -> None:
    now = int(time.time())
    payload = dict(payload)
    payload["ts"] = now
    payload["expires_at"] = now + int(payload.get("expires_in") or 0)
    TOKEN_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    TOKEN_FILE.chmod(0o600)


def _read_token() -> dict:
    if not TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _token_request(data: dict) -> dict:
    req = urllib.request.Request(
        API + "/oauth/token",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Authorization": _basic(),
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Pinterest отбил токен: %s %s" % (e.code, e.read().decode()[:300]))


def token() -> str:
    t = _read_token()
    if not t.get("access_token"):
        die("нет токена: сначала `auth-url`, потом `exchange --code …`")
    if int(t.get("expires_at") or 0) - 3600 < time.time():
        if not t.get("refresh_token"):
            die("access истёк и refresh нет — получи токен заново")
        fresh = _token_request({"grant_type": "refresh_token",
                                "refresh_token": t["refresh_token"]})
        fresh.setdefault("refresh_token", t["refresh_token"])
        _save_token(fresh)
        t = _read_token()
    return t["access_token"]


def api(method: str, path: str, payload: dict | None = None) -> dict:
    url = API + path
    data = None
    headers = {"Authorization": "Bearer " + token()}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode()[:500]
        raise RuntimeError("Pinterest %s %s: %s" % (e.code, path, text))


def state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def save_state(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def frontmatter(path: pathlib.Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    try:
        fm = raw.split("---", 2)[1]
    except IndexError:
        return {}
    meta = {}
    for line in fm.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def pin_for(slug: str) -> dict:
    """Пин из статьи: картинка 1000×1500, заголовок, описание, ссылка."""
    path = POSTS / (slug + ".md")
    if not path.exists():
        die("нет статьи %s" % slug)
    meta = frontmatter(path)
    pin = (meta.get("pin") or "").strip()
    cover = (meta.get("cover") or "").strip()
    rel = pin or cover
    if not rel:
        die("у статьи %s нет ни pin, ни cover" % slug)
    image = ROOT / "static" / rel.replace("/assets/", "", 1)
    if not image.exists():
        die("картинки нет на диске: %s" % image)
    title = (meta.get("title") or slug)[:100]
    desc = (meta.get("summary") or "").strip()
    desc = re.sub(r"\s+", " ", desc)
    if len(desc) > 480:
        desc = desc[:477].rsplit(" ", 1)[0] + "…"
    return {
        "slug": slug,
        "title": title,
        "description": desc,
        "link": "https://geekovski.ru/%s.html" % slug,
        "image": image,
        "image_url": "https://geekovski.ru/assets/img/" + image.name,
    }


def create_pin(board_id: str, item: dict) -> dict:
    payload = {
        "board_id": board_id,
        "title": item["title"],
        "description": item["description"],
        "link": item["link"],
        "media_source": {"source_type": "image_url", "url": item["image_url"]},
    }
    return api("POST", "/pins", payload)


def cmd_auth_url(_a) -> int:
    cid, _ = app()
    q = urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": ",".join(SCOPES), "state": "geekovski",
    })
    print("https://www.pinterest.com/oauth/?%s" % q)
    print("\nПосле согласия браузер уйдёт на %s?code=…&state=geekovski" % REDIRECT)
    print("Скопируй параметр code целиком и передай: --code <code>")
    return 0


def cmd_exchange(a) -> int:
    data = _token_request({"grant_type": "authorization_code", "code": a.code,
                           "redirect_uri": REDIRECT})
    _save_token(data)
    print("токен сохранён:", TOKEN_FILE)
    return 0


def cmd_check(_a) -> int:
    me = api("GET", "/user_account")
    print("аккаунт:", me.get("username"), "|", me.get("account_type"),
          "|", me.get("profile_url"))
    boards = api("GET", "/boards?page_size=25")
    print("досок:", len(boards.get("items", [])))
    print("⚠ приложение в Trial → пины видны только тебе (sandbox), пока не пройдёт Standard")
    return 0


def cmd_boards(_a) -> int:
    boards = api("GET", "/boards?page_size=100")
    for b in boards.get("items", []):
        print("%-30s %s" % (b["id"], b["name"]))
    return 0


def cmd_pin(a) -> int:
    item = pin_for(a.slug)
    res = create_pin(a.board, item)
    st = state()
    st[a.slug] = {"pin_id": res.get("id"), "board": a.board,
                  "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    save_state(st)
    print("пин:", res.get("id"), "→", item["link"])
    return 0


def cmd_bulk(a) -> int:
    st = state()
    done = 0
    for path in sorted(POSTS.glob("*.md"), reverse=True):
        slug = path.stem
        if slug in st:
            continue
        meta = frontmatter(path)
        if meta.get("status") == "draft" or meta.get("kind") in ("digest", "calendar"):
            continue
        if not meta.get("pin"):
            continue
        if done >= a.limit:
            break
        res = create_pin(a.board, pin_for(slug))
        st[slug] = {"pin_id": res.get("id"), "board": a.board,
                    "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
        save_state(st)
        done += 1
        print("✓", slug, res.get("id"))
        if a.pause:
            time.sleep(a.pause)
    print("поставлено пинов:", done)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Пины GEEKOVSKI в Pinterest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth-url").set_defaults(func=cmd_auth_url)
    ex = sub.add_parser("exchange")
    ex.add_argument("--code", required=True)
    ex.set_defaults(func=cmd_exchange)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("boards").set_defaults(func=cmd_boards)
    pn = sub.add_parser("pin")
    pn.add_argument("--slug", required=True)
    pn.add_argument("--board", required=True)
    pn.set_defaults(func=cmd_pin)
    bl = sub.add_parser("bulk")
    bl.add_argument("--board", required=True)
    bl.add_argument("--limit", type=int, default=10)
    bl.add_argument("--pause", type=float, default=3.0, help="пауза между пинами, сек")
    bl.set_defaults(func=cmd_bulk)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
