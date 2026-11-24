#!/usr/bin/env python3
"""Получить OAuth-токены Яндекса для отчётов по блогу.

Запускай у себя в терминале (не через агента): токен появится в браузере,
введёшь код — скрипт сам запишет ~/.hermes/profiles/geekovski/analytics.json.

Создай приложение на https://oauth.yandex.ru/client/new и включи права:
  • Яндекс.Метрика — «Получение статистики» (metrika:read)
  • Яндекс.Вебмастер — «Получение данных» (webmaster:hostinfo, webmaster:verify)

  python3 tools/yandex_auth.py --client-id XXX --client-secret YYY

Скрипт напечатает ссылку, откроет браузер и дождётся кода.
"""
import argparse
import json
import os
import pathlib
import urllib.parse
import urllib.request

HOME = pathlib.Path.home() / ".hermes/profiles/geekovski"
CONF = HOME / "analytics.json"
TOKEN_URL = "https://oauth.yandex.ru/token"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--client-secret", default=None)
    ap.add_argument("--code", default=None,
                    help="код подтверждения; без него скрипт спросит интерактивно")
    ap.add_argument("--counter-id", type=int, default=114070859)
    a = ap.parse_args()

    # ключи приложения можно держать в .env профиля — тогда в терминале их не видно
    env_path = HOME / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    a.client_id = a.client_id or os.environ.get("YANDEX_CLIENT_ID")
    a.client_secret = a.client_secret or os.environ.get("YANDEX_CLIENT_SECRET")
    if not (a.client_id and a.client_secret):
        raise SystemExit("нет client id/secret: положи YANDEX_CLIENT_ID и "
                         "YANDEX_CLIENT_SECRET в ~/.hermes/profiles/geekovski/.env")

    auth_url = ("https://oauth.yandex.ru/authorize?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": a.client_id,
        "force_confirm": "yes",
    }))
    print("\n1. Открой ссылку и разреши доступ:")
    print("   " + auth_url)
    print("\n2. Яндекс покажет код подтверждения — скопируй его целиком.")
    code = a.code or input("\nКод: ").strip()

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": a.client_id,
        "client_secret": a.client_secret,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.loads(r.read().decode())

    token = tok.get("access_token")
    if not token:
        raise SystemExit("не получили токен: %s" % tok)

    conf = {}
    if CONF.exists():
        conf = json.loads(CONF.read_text(encoding="utf-8"))
    # один токен Яндекса работает и для Метрики, и для Вебмастера
    conf.update({"webmaster_token": token, "metrika_token": token,
                 "counter_id": a.counter_id})

    # сразу проверяем, что токен видит Вебмастер, и запоминаем user_id/host_id:
    # без них переобход и отчёты по хосту не поедут
    def get(url):
        req = urllib.request.Request(url, headers={"Authorization": "OAuth " + token})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    try:
        user = get("https://api.webmaster.yandex.net/v4/user")
        uid = user["user_id"]
        hosts = get("https://api.webmaster.yandex.net/v4/user/%d/hosts" % uid)
        conf["user_id"] = uid
        print("\nВебмастер: пользователь %s" % uid)
        for h in hosts.get("hosts", []):
            mark = " ← наш" if "geekovski" in h.get("unicode_host_url", "") else ""
            print("  %s  %s%s" % (h.get("host_id"), h.get("unicode_host_url"), mark))
            if "geekovski" in h.get("unicode_host_url", ""):
                conf["host_id"] = h["host_id"]
                conf["host_url"] = h.get("unicode_host_url")
        if not conf.get("host_id"):
            print("  ! geekovski.ru в списке нет — добавь сайт в Вебмастере")
    except Exception as exc:
        print("\nВебмастер не ответил: %s — токен сохранён, проверь права webmaster:hostinfo" % exc)
    CONF.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nГотово. Токен сохранён в", CONF)
    print("Проверка: python3 tools/seo_report.py --days 7")


if __name__ == "__main__":
    main()
