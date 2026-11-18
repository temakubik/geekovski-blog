#!/usr/bin/env python3
"""Картинки через WaveSpeed — одна ручка на весь каталог моделей.

    python3 tools/wavespeed_img.py balance
    python3 tools/wavespeed_img.py models --type text-to-image --search seedream
    python3 tools/wavespeed_img.py schema bytedance/seedream-v5.5
    python3 tools/wavespeed_img.py price -m bytedance/seedream-v5.5 -p "..." -s 1600*900
    python3 tools/wavespeed_img.py run -m bytedance/seedream-v5.5 \
        -p "foggy street at night, neon" -s 1600*900 -o static/img/test.jpg

Ключ: WAVESPEED_API_KEY из окружения, иначе из
~/.hermes/profiles/geekovski/.env (положить: WAVESPEED_API_KEY=wsk_...).

Устройство API (v3): POST /api/v3/<model> создаёт задачу и сразу отдаёт id,
GET /api/v3/predictions/<id>/result опрашивается до status=completed,
готовые ссылки лежат в data.outputs. Ответ всегда в конверте
{"code":200,"data":{...},"message":...} — code != 200 это ошибка.

Перед новым размером/параметром смотрите схему модели: лишние ключи
платформа игнорирует, но деньги за прогон всё равно списывает.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.wavespeed.ai"
ENV_FILE = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".env"

# Модели, на которых стоит начинать: цена и назначение (цены — wavespeed.ai/pricing).
KNOWN = {
    "bytedance/seedream-v5.5": "$0.02 — дефолт для обложек и кадров блога",
    "google/nano-banana-2.1/text-to-image": "$0.04 — лучше держит текст и детали устройства",
    "openai/gpt-image-2.6-sunburst/text-to-image": "$0.045 — GPT-Image, как в OpenAI",
    "wavespeed-ai/z-image/turbo": "~$0.005 — самый дешёвый, для черновиков",
}


def load_key() -> str:
    key = os.environ.get("WAVESPEED_API_KEY", "").strip()
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("WAVESPEED_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("$"):
                    return val
    sys.exit(
        "✗ нет WAVESPEED_API_KEY ни в окружении, ни в "
        f"{ENV_FILE}\n  взять ключ: https://wavespeed.ai/accesskey"
    )


def call(method: str, path: str, body: dict | None = None, key: str = "", timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Платформа помечает клиента по этим трём заголовкам — тот же набор, что у их CLI.
            "X-Client-Name": "geekovski-blog",
            "X-Client-Version": "1.0.0",
            "X-Client-OS": sys.platform,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read().decode())
            detail = err.get("message") or ""
            if err.get("error_code"):
                detail += f" [{err['error_code']}]"
        except Exception:
            pass
        sys.exit(f"✗ {method} {path}: {e.code} {e.reason} {detail}".rstrip())
    except urllib.error.URLError as e:
        sys.exit(f"✗ сеть: {method} {path}: {e.reason}")
    if payload.get("code") != 200:
        sys.exit(f"✗ {method} {path}: {payload.get('message') or payload}")
    return payload.get("data")


def model_index(key: str) -> list[dict]:
    data = call("GET", "/api/v3/models", key=key)
    return data if isinstance(data, list) else data.get("models", [])


def cmd_models(args, key):
    models = model_index(key)
    words = [w.lower() for w in (args.search.split() if args.search else [])]
    hits = []
    for m in models:
        mid = m.get("model_id") or m.get("id") or ""
        mtype = (m.get("type") or m.get("category") or "").lower()
        if args.type and args.type.lower() not in mtype:
            continue
        blob = f"{mid} {m.get('name', '')} {m.get('description', '')}".lower()
        if words and not all(w in blob for w in words):
            continue
        hits.append((mid, mtype, m.get("base_price") or m.get("price") or ""))
    for mid, mtype, price in hits[: args.limit]:
        note = KNOWN.get(mid, "")
        print(f"{mid:<52} {mtype:<18} {str(price):<10} {note}".rstrip())
    print(f"\nвсего: {len(hits)} (показано {min(len(hits), args.limit)})")


def find_model(models: list[dict], model_id: str) -> dict | None:
    for m in models:
        if (m.get("model_id") or m.get("id")) == model_id:
            return m
    return None


def cmd_schema(args, key):
    models = model_index(key)
    m = find_model(models, args.model)
    if not m:
        sys.exit(f"✗ нет модели {args.model} в каталоге (python3 tools/wavespeed_img.py models)")
    print(json.dumps(m, ensure_ascii=False, indent=2))
    print(f"\nплейграунд: https://wavespeed.ai/models/{args.model}", file=sys.stderr)


def build_input(args) -> dict:
    if args.input:
        inputs = json.loads(args.input)
    else:
        inputs = {}
        if args.prompt:
            inputs["prompt"] = args.prompt
        if args.size:
            inputs["size"] = args.size
        if args.aspect:
            inputs["aspect_ratio"] = args.aspect
    if args.extra:
        inputs.update(json.loads(args.extra))
    if not args.input and not inputs.get("prompt") and not inputs.get("image"):
        sys.exit("✗ нужен --prompt (или --input / --extra с полным набором полей)")
    return inputs


def cmd_price(args, key):
    inputs = build_input(args)
    data = call("POST", "/api/v3/model/price", {"model_id": args.model, "input": inputs}, key=key)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_balance(args, key):
    data = call("GET", "/api/v3/balance", key=key)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_run(args, key):
    inputs = build_input(args)
    task = call("POST", f"/api/v3/{args.model}", inputs, key=key, timeout=90)
    pid = task.get("id") if isinstance(task, dict) else None
    if not pid:
        sys.exit(f"✗ платформа не вернула id задачи: {task}")
    print(f"задача {pid} отправлена ({args.model})", file=sys.stderr)

    deadline = time.time() + args.timeout
    result = None
    while True:
        result = call("GET", f"/api/v3/predictions/{pid}/result", key=key)
        status = (result or {}).get("status", "")
        if status not in ("created", "processing"):
            break
        if time.time() + args.interval > deadline:
            sys.exit(
                f"✗ задача {pid} ещё идёт после {args.timeout}s — она не потеряна, "
                f"проверить: get_prediction / этот же id на wavespeed.ai"
            )
        time.sleep(args.interval)

    if (result or {}).get("status") != "completed":
        sys.exit(f"✗ задача {pid}: {result.get('status')} {result.get('error') or ''}".rstrip())

    outputs = result.get("outputs") or []
    for url in outputs:
        print(url)
    if not outputs:
        sys.exit(f"✗ задача {pid} завершена, но outputs пуст: {result}")

    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        ext = pathlib.Path(outputs[0].split("?")[0]).suffix or ".png"
        if not out.suffix:
            out = out.with_suffix(ext)
        with urllib.request.urlopen(outputs[0], timeout=120) as resp:
            out.write_bytes(resp.read())
        print(f"→ {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} "
              f"({out.stat().st_size // 1024} КБ)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="WaveSpeed: картинки, цены и каталог моделей")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("models", help="каталог моделей с поиском")
    p.add_argument("--type", help="text-to-image, image-to-image, text-to-video…")
    p.add_argument("--search", help="слова в id/названии/описании")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("schema", help="реальная схема входов модели")
    p.add_argument("model")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("price", help="оценка стоимости, без списания")
    p.add_argument("-m", "--model", required=True)
    p.add_argument("-p", "--prompt")
    p.add_argument("-s", "--size", help="например 1600*900")
    p.add_argument("--aspect", help="например 16:9, если модель берёт aspect_ratio")
    p.add_argument("--input", help="полный JSON входов вместо -p/-s")
    p.add_argument("--extra", help="JSON, который подмешать к -p/-s")
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("balance", help="баланс аккаунта")
    p.set_defaults(func=cmd_balance)

    p = sub.add_parser("run", help="сгенерировать и скачать")
    p.add_argument("-m", "--model", default="bytedance/seedream-v5.5")
    p.add_argument("-p", "--prompt")
    p.add_argument("-s", "--size", help="например 1600*900")
    p.add_argument("--aspect", help="например 16:9")
    p.add_argument("--input", help="полный JSON входов вместо -p/-s")
    p.add_argument("--extra", help="JSON, который подмешать к -p/-s")
    p.add_argument("-o", "--out", help="файл для скачивания, относительно корня репозитория")
    p.add_argument("--interval", type=float, default=2.0, help="пауза между опросами, с")
    p.add_argument("--timeout", type=float, default=300.0, help="сколько ждать задачу, с")
    p.set_defaults(func=cmd_run)

    args = ap.parse_args()
    args.func(args, load_key())


if __name__ == "__main__":
    main()
