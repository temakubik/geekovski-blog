#!/usr/bin/env python3
"""Генерация картинок по паспортам персонажей GEEKOVSKI.

Читает content/personas/<slug>.md (frontmatter: anchor, style, negative, shots)
и складывает кадры в content/personas/img/<slug>/<shot>.png.

    python3 tools/gen_persona.py --slug seva --shot avatar
    python3 tools/gen_persona.py --slug seva --shot all
    python3 tools/gen_persona.py --slug all --shot avatar
    python3 tools/gen_persona.py --slug mark --shot desk --dry-run   # только промпт

Модель и размеры — Images API (b64_json). Ключ берётся из OPENAI_API_KEY,
при отсутствии — из ~/.hermes/profiles/geekovski/.env.
"""

import argparse
import base64
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PERSONAS = ROOT / "content" / "personas"
OUT = PERSONAS / "img"
MODEL = "gpt-image-2.5-sunburst"
API = "https://api.openai.com/v1/images/generations"
SIZES = {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}


def load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("✗ нет OPENAI_API_KEY ни в окружении, ни в профиле")


def load_passport(slug: str) -> dict:
    path = PERSONAS / f"{slug}.md"
    if not path.exists():
        sys.exit(f"✗ нет паспорта: {path}")
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        sys.exit(f"✗ в {path.name} нет frontmatter")
    _, fm, _ = raw.split("---", 2)
    data = yaml.safe_load(fm)
    for field in ("anchor", "style", "shots"):
        if not data.get(field):
            sys.exit(f"✗ в паспорте {path.name} пустое поле {field}")
    return data


def build_prompt(p: dict, shot: dict) -> str:
    parts = [f"{shot['scene'].strip().rstrip('.')}."]
    parts.append(f"The person: {p['anchor'].strip().rstrip('.')}.")
    parts.append(f"Style: {p['style'].strip().rstrip('.')}.")
    if p.get("negative"):
        parts.append(f"Avoid: {p['negative'].strip().rstrip('.')}.")
    return " ".join(parts)


def generate(prompt: str, size: str, key: str, quality: str = "high") -> bytes:
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
    }).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ API {e.code}: {e.read().decode(errors='ignore')[:600]}")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"✗ сеть: {e}")
    item = payload["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as r:
            return r.read()
    sys.exit("✗ в ответе нет ни b64_json, ни url")


def save_url(url: str, slug: str, shot: str) -> None:
    """Скачать готовый кадр (Doop и т.п.) в папку персонажа: .webp + .jpg для ВК."""
    if shot == "all":
        sys.exit("✗ для --save-url нужен конкретный --shot (avatar, desk, screening…)")
    folder = OUT / slug
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"✗ не скачалось: {e}")
    webp = folder / f"{shot}.webp"
    webp.write_bytes(data)
    print(f"✓ {webp.relative_to(ROOT)}  ({len(data) // 1024} КБ)")
    jpg = folder / f"{shot}.jpg"
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(webp), "--out", str(jpg)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"✓ {jpg.relative_to(ROOT)}")
    else:
        print("! sips не найден: JPG не собран, конвертируй вручную (ВК не принимает WebP)")


def main():
    ap = argparse.ArgumentParser(description="Картинки по паспортам персонажей")
    ap.add_argument("--slug", required=True, help="seva | mark | anya | all")
    ap.add_argument("--shot", default="all", help="id кадра из паспорта или all")
    ap.add_argument("--dry-run", action="store_true", help="только показать промпты")
    ap.add_argument("--quality", default="high", help="high | medium | low")
    ap.add_argument("--save-url", help="скачать уже сгенерированный кадр (например, из Doop) в папку персонажа")
    args = ap.parse_args()

    if args.save_url:
        save_url(args.save_url, args.slug, args.shot)
        return

    slugs = ["seva", "mark", "anya"] if args.slug == "all" else [args.slug]
    key = "" if args.dry_run else load_key()
    total = 0

    for slug in slugs:
        p = load_passport(slug)
        shots = p["shots"]
        if args.shot != "all":
            shots = [s for s in shots if s["id"] == args.shot]
            if not shots:
                ids = ", ".join(s["id"] for s in p["shots"])
                sys.exit(f"✗ у «{slug}» нет кадра «{args.shot}» (есть: {ids})")
        for shot in shots:
            prompt = build_prompt(p, shot)
            size = SIZES.get(str(shot.get("ratio", "1:1")), "1024x1024")
            print(f"\n— {slug}/{shot['id']}  {size}")
            print(prompt)
            if args.dry_run:
                continue
            data = generate(prompt, size, key, args.quality)
            path = OUT / slug / f"{shot['id']}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(f"✓ {path.relative_to(ROOT)}  ({len(data) // 1024} КБ)")
            total += 1

    if not args.dry_run:
        print(f"\nготово кадров: {total}")


if __name__ == "__main__":
    main()
