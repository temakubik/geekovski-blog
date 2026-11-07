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
import pathlib
import urllib.parse
import urllib.request

HOME = pathlib.Path.home() / ".hermes/profiles/geekovski"
CONF = HOME / "analytics.json"
TOKEN_URL = "https://oauth.yandex.ru/token"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    ap.add_argument("--counter-id", type=int, default=114070859)
    a = ap.parse_args()

    auth_url = ("https://oauth.yandex.ru/authorize?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": a.client_id,
        "force_confirm": "yes",
    }))
    print("\n1. Открой ссылку и разреши доступ:")
    print("   " + auth_url)
    print("\n2. Яндекс покажет код подтверждения — скопируй его целиком.")
    code = input("\nКод: ").strip()

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
    CONF.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nГотово. Токен сохранён в", CONF)
    print("Проверка: python3 tools/seo_report.py --days 7")


if __name__ == "__main__":
    main()
