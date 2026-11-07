#!/usr/bin/env python3
"""Отчёт по развитию блога: Яндекс.Вебмастер + Метрика.

Скрипт собирает цифры из API и печатает короткий отчёт для Telegram.
Токены берёт из ~/.hermes/profiles/geekovski/analytics.json:

  {
    "webmaster_token": "…",
    "metrika_token": "…",
    "counter_id": 114070859
  }

  python3 tools/seo_report.py            # отчёт за последние 7 дней
  python3 tools/seo_report.py --days 30  # за 30 дней
  python3 tools/seo_report.py --check    # только проверить, что токены живые

Пока токенов нет — печатает, чего не хватает, и не падает.
"""
import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

HOME = pathlib.Path.home() / ".hermes/profiles/geekovski"
CONF = HOME / "analytics.json"
HOST = "geekovski.ru"


def load_conf():
    if not CONF.exists():
        return {}
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        return {}


def api(url, token, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "OAuth " + token})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def webmaster(token, days):
    """Индексация и поисковые показы/клики за период."""
    user = api("https://api.webmaster.yandex.net/v4/user", token)
    uid = user["user_id"]
    hosts = api("https://api.webmaster.yandex.net/v4/user/%s/hosts" % uid, token)
    host = next((h for h in hosts.get("hosts", [])
                 if HOST in (h.get("unicode_host_url") or "")), None)
    if not host:
        return {"error": "домен geekovski.ru не добавлен в Вебмастер"}
    hid = urllib.parse.quote(host["host_id"], safe="")

    base = "https://api.webmaster.yandex.net/v4/user/%s/hosts/%s" % (uid, hid)
    out = {}
    try:
        summary = api(base + "/summary", token)
        out["indexed"] = summary.get("searchable_pages_count")
        out["excluded"] = summary.get("excluded_pages_count")
    except Exception as e:
        out["indexed_error"] = str(e)[:60]
    try:
        to = date.today()
        frm = to - timedelta(days=days)
        hist = api(base + "/search-queries/all/history", token, {
            "query_indicator": ["TOTAL_SHOWS", "TOTAL_CLICKS"],
            "date_from": frm.isoformat(), "date_to": to.isoformat(),
        })
        ind = hist.get("indicators", {})
        shows = sum(p["value"] for p in ind.get("TOTAL_SHOWS", []))
        clicks = sum(p["value"] for p in ind.get("TOTAL_CLICKS", []))
        out["shows"] = int(shows)
        out["clicks"] = int(clicks)
    except Exception as e:
        out["queries_error"] = str(e)[:60]
    return out


def metrika(token, counter, days):
    """Визиты, посетители, просмотры из Метрики."""
    to = date.today()
    frm = to - timedelta(days=days - 1)
    params = {"ids": counter, "metrics": "ym:s:visits,ym:s:users,ym:s:pageviews",
              "date1": frm.isoformat(), "date2": to.isoformat()}
    url = "https://api-metrika.yandex.net/stat/v1/data?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "OAuth " + token})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.loads(r.read().decode())
    tot = (d.get("totals") or [0, 0, 0])
    return {"visits": int(tot[0]), "users": int(tot[1]), "views": int(tot[2])}


def fmt(n):
    return f"{n:,}".replace(",", " ") if isinstance(n, int) else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    conf = load_conf()
    have_wm = bool(conf.get("webmaster_token"))
    have_ym = bool(conf.get("metrika_token")) and bool(conf.get("counter_id"))

    if not (have_wm or have_ym):
        print("Нет доступа к статистике: заполни %s" % CONF)
        print("Нужно: webmaster_token (Яндекс.Вебмастер) и metrika_token + counter_id (Метрика).")
        sys.exit(2)

    lines = ["Развитие GEEKOVSKI за %d дн." % a.days]

    if have_ym:
        try:
            m = metrika(conf["metrika_token"], conf["counter_id"], a.days)
            lines.append("Посещения: %s · посетители: %s · просмотры: %s"
                         % (fmt(m["visits"]), fmt(m["users"]), fmt(m["views"])))
        except urllib.error.HTTPError as e:
            lines.append("Метрика: ошибка %s (токен или счётчик)" % e.code)
        except Exception as e:
            lines.append("Метрика: %s" % str(e)[:60])

    if have_wm:
        try:
            w = webmaster(conf["webmaster_token"], a.days)
            if w.get("error"):
                lines.append("Вебмастер: " + w["error"])
            else:
                lines.append("В индексе: %s стр. · исключено: %s"
                             % (fmt(w.get("indexed")), fmt(w.get("excluded"))))
                lines.append("Показы в поиске: %s · клики: %s"
                             % (fmt(w.get("shows")), fmt(w.get("clicks"))))
                for k in ("indexed_error", "queries_error"):
                    if w.get(k):
                        lines.append("%s: %s" % (k, w[k]))
        except urllib.error.HTTPError as e:
            lines.append("Вебмастер: ошибка %s (токен просрочен?)" % e.code)

    print("\n".join(lines))


if __name__ == "__main__":
    main()
