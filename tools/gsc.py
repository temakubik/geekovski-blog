#!/usr/bin/env python3
"""Google Search Console через сервисный аккаунт.

    python3 tools/gsc.py sites                 # какие ресурсы доступны
    python3 tools/gsc.py sitemaps              # sitemap в кабинете
    python3 tools/gsc.py submit-sitemap        # добавить sitemap.xml
    python3 tools/gsc.py pages --days 7        # страницы: показы, клики, CTR, позиция
    python3 tools/gsc.py queries --days 7      # запросы
    python3 tools/gsc.py inspect <url>         # статус индексации конкретной страницы

Ключ сервисного аккаунта: ~/.hermes/profiles/geekovski/gsc-key.json (chmod 600).
Сервисный аккаунт должен быть добавлен в Search Console как пользователь
с полным доступом — иначе API отвечает 403.

JWT подписывается локально (cryptography), токен живёт час и нигде не хранится.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

KEY = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / "gsc-key.json"
SITE = "https://geekovski.ru/"
SCOPES = {
    "webmasters": "https://www.googleapis.com/auth/webmasters",
    "inspect": "https://www.googleapis.com/auth/webmasters.readonly",
}
TOKEN_URL = "https://oauth2.googleapis.com/token"


def die(msg: str) -> NoReturn:
    sys.stderr.write("✗ %s\n" % msg)
    raise SystemExit(1)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


_TOKENS: dict = {}


def access_token(scope: str = SCOPES["webmasters"]) -> str:
    """Токен живёт час; кэшируем в процессе, чтобы пачка URL не тянула его каждый раз."""
    hit = _TOKENS.get(scope)
    if hit and hit[1] > time.time() + 60:
        return hit[0]
    if not KEY.exists():
        die("нет ключа %s" % KEY)
    info = json.loads(KEY.read_text(encoding="utf-8"))
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": info["client_email"], "scope": scope, "aud": TOKEN_URL,
              "iat": now, "exp": now + 3600}
    unsigned = "%s.%s" % (_b64(json.dumps(header).encode()),
                          _b64(json.dumps(claims).encode()))
    key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
    sig = key.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
    assertion = "%s.%s" % (unsigned, _b64(sig))
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.loads(r.read().decode())["access_token"]
            _TOKENS[scope] = (tok, time.time() + 3600)
            return tok
    except urllib.error.HTTPError as e:
        die("Google не выдал токен: %s %s" % (e.code, e.read().decode()[:300]))


def api(method: str, path: str, payload: dict | None = None, scope: str = SCOPES["webmasters"]):
    url = "https://searchconsole.googleapis.com" + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + access_token(scope),
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        if e.code == 403:
            die("403: сервисный аккаунт не добавлен в Search Console или нет прав.\n" + body)
        die("%s %s → %s %s" % (method, path, e.code, body))


def cmd_sites(_a) -> int:
    d = api("GET", "/webmasters/v3/sites")
    for s in d.get("siteEntry", []):
        print("%-40s %s" % (s.get("siteUrl"), s.get("permissionLevel")))
    if not d.get("siteEntry"):
        print("пусто — сервисный аккаунт не видит ни одного ресурса")
    return 0


def cmd_sitemaps(_a) -> int:
    q = urllib.parse.quote(SITE, safe="")
    d = api("GET", "/webmasters/v3/sites/%s/sitemaps" % q)
    items = d.get("sitemap", [])
    print("sitemap в кабинете: %d" % len(items))
    for s in items:
        print("  %s | последнее чтение: %s | предупреждений: %s | ошибок: %s" % (
            s.get("path"), s.get("lastDownloaded"), s.get("warnings"), s.get("errors")))
    return 0


def cmd_submit(_a) -> int:
    q = urllib.parse.quote(SITE, safe="")
    sm = urllib.parse.quote(SITE + "sitemap.xml", safe="")
    api("PUT", "/webmasters/v3/sites/%s/sitemaps/%s" % (q, sm))
    print("sitemap отправлен:", SITE + "sitemap.xml")
    return 0


def _range(days: int) -> tuple[str, str]:
    import datetime as dt
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _query(dim: str, days: int, limit: int) -> list:
    frm, to = _range(days)
    body = {"startDate": frm, "endDate": to, "dimensions": [dim], "rowLimit": limit}
    d = api("POST", "/webmasters/v3/sites/%s/searchAnalytics/query"
            % urllib.parse.quote(SITE, safe=""), body)
    return d.get("rows", [])


def _print_rows(rows, key_name: str) -> None:
    if not rows:
        print("данных нет: Google ещё не показывал сайт по этому срезу")
        return
    print("%-60s %8s %8s %7s %8s" % (key_name, "показы", "клики", "CTR", "поз."))
    for r in rows:
        keys = r.get("keys", [""])[0]
        ctr = r.get("ctr", 0) * 100
        print("%-60s %8d %8d %6.1f%% %8.1f" % (keys[:60], r.get("impressions", 0),
                                               r.get("clicks", 0), ctr, r.get("position", 0)))


def cmd_pages(a) -> int:
    _print_rows(_query("page", a.days, a.limit), "страница")
    return 0


def cmd_queries(a) -> int:
    _print_rows(_query("query", a.days, a.limit), "запрос")
    return 0


def cmd_inspect(a) -> int:
    d = api("POST", "/v1/urlInspection/index:inspect", {
        "inspectionUrl": a.url, "siteUrl": SITE,
        "languageCode": "ru-RU"}, scope=SCOPES["inspect"])
    res = d.get("inspectionResult", {}).get("indexStatusResult", {})
    print("URL:", a.url)
    print("вердикт:", res.get("verdict"))
    print("покрытие:", res.get("coverageState"))
    print("робот:", res.get("robotsTxtState"), "| индексация разрешена:", res.get("indexingState"))
    print("последний обход:", res.get("lastCrawlTime"))
    print("canonical Google:", res.get("googleCanonical"))
    print("canonical страница:", res.get("userCanonical"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Search Console из терминала")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sites").set_defaults(func=cmd_sites)
    sub.add_parser("sitemaps").set_defaults(func=cmd_sitemaps)
    sub.add_parser("submit-sitemap").set_defaults(func=cmd_submit)
    for name, fn in (("pages", cmd_pages), ("queries", cmd_queries)):
        p = sub.add_parser(name)
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--limit", type=int, default=25)
        p.set_defaults(func=fn)
    ins = sub.add_parser("inspect")
    ins.add_argument("url")
    ins.set_defaults(func=cmd_inspect)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
