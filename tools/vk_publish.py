#!/usr/bin/env python3
"""Публикация статей GEEKOVSKI в сообщество ВКонтакте.

Работает через VK API (wall.post) от имени сообщества — без браузера и без
основного профиля автора. Ссылка на статью уходит вложением: VK сам собирает
сниппет из og:title / og:description / og:image страницы.

Примеры:
    # посмотреть, что уйдёт в пост (ничего не публикует)
    python3 tools/vk_publish.py --slug 2026-11-14-1000-google-umnye-ochki --dry-run

    # опубликовать сейчас
    python3 tools/vk_publish.py --slug <slug> --post

    # поставить в отложенные на 15 ноября, 10:00
    python3 tools/vk_publish.py --slug <slug> --publish-at "2026-11-15 10:00"

    # отправить отредактированный вручную текст
    python3 tools/vk_publish.py --slug <slug> --text-file content/vk/<slug>.txt --post

Токен и id сообщества берутся из окружения:
    VK_GROUP_TOKEN — ключ доступа сообщества (Управление → Дополнительно → Работа с API)
    VK_GROUP_ID    — числовой id сообщества без минуса (или screen_name)
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import NoReturn

ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
VK_DIR = ROOT / "content" / "vk"
STATE = VK_DIR / "posted.json"
SITE = "https://geekovski.ru"
API_HOSTS = ("https://api.vk.ru/method/", "https://api.vk.com/method/")
API_V = "5.199"

# ВКонтакте не понимает markdown: жирный, звёздочки, заголовки — всё это
# остаётся мусором в тексте. Поэтому текст собирается из frontmatter, а не
# вырезается из тела статьи.
CAT_TAGS = {
    "ai": ["нейросети", "ИИ"],
    "gadgets": ["гаджеты", "технологии"],
    "games": ["игры", "гейминг"],
    "movies": ["кино"],
    "series": ["сериалы"],
    "vr": ["VR"],
    "xbox": ["Xbox", "игры"],
    "playstation": ["PlayStation", "игры"],
    "tech": ["технологии"],
}

# Коды, при которых повтор запроса безопасен: VK ничего не создал.
RETRY_CODES = {6: 3, 9: 60, 10: 60}


def die(msg: str, code: int = 1) -> NoReturn:
    sys.stdout.flush()
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


def parse_frontmatter(path: pathlib.Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    meta = {}
    if raw.startswith("---"):
        try:
            _, fm, _ = raw.split("---", 2)
        except ValueError:
            die(f"битый frontmatter: {path}")
        for line in fm.strip().splitlines():
            if ":" not in line or line.lstrip().startswith("#"):
                continue
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    meta.setdefault("slug", path.stem)
    return meta


def first_sentence(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = re.search(r"^(.{40,%d}?[.!?…])(\s|$)" % limit, text)
    return m.group(1) if m else text[:limit].rstrip()


def hashtags(meta: dict) -> str:
    tags = []
    cat = (meta.get("category") or "tech").strip().lower()
    tags += CAT_TAGS.get(cat, ["технологии"])
    # латинские названия из заголовка — рабочие теги ВК (Google, Xbox, GTA)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9&\-]{1,15}", meta.get("title", "")):
        if word.lower() in {"the", "and", "for", "pro", "max", "vs"}:
            continue
        tag = word.replace("-", "").replace("&", "")
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 5:
            break
    out = []
    for t in tags[:5]:
        t = re.sub(r"\s+", "", t)
        if t and f"#{t}" not in out:
            out.append(f"#{t}")
    return " ".join(out)


def build_text(meta: dict) -> str:
    """Короткий пост под ВК: хук, три факта, ссылка уходит сниппетом."""
    title = meta.get("title", "").strip()
    summary = meta.get("summary", "").strip()
    tldr = [p.strip() for p in meta.get("tldr", "").split("|") if p.strip()]

    parts = []
    if title:
        parts.append(title)
    if summary:
        parts.append(first_sentence(summary))
    if tldr:
        parts.append("\n".join(f"• {p}" for p in tldr[:3]))
    parts.append("Полный разбор — по ссылке ниже.")
    tags = hashtags(meta)
    if tags:
        parts.append(tags)
    return "\n\n".join(parts).strip()


def article_url(meta: dict) -> str:
    canonical = meta.get("canonical") or meta.get("url")
    if canonical:
        return canonical
    return f"{SITE}/{meta['slug']}.html"


def api(method: str, params: dict, token: str, _retries: int = 0) -> dict:
    """POST на VK API. Токен уходит и заголовком (новая схема), и в теле (старая)."""
    data = dict(params)
    data["v"] = API_V
    body = urllib.parse.urlencode(data).encode()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "geekovski-blog/1.0 (+https://geekovski.ru)",
    }
    payload: dict = {"error": {"error_code": -1, "error_msg": "запрос не выполнен"}}

    for host in API_HOSTS:
        for attempt in range(3):
            req = urllib.request.Request(host + method, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    payload = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                raw = e.read().decode(errors="ignore")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"error": {"error_code": e.code, "error_msg": raw[:200]}}
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                payload = {"error": {"error_code": -1, "error_msg": f"сеть: {e}"}}
            break

        err = payload.get("error", {})
        # 5 — «токен не принят»: пробуем второй хост, прежде чем сдаваться.
        if err.get("error_code") == 5 and host is not API_HOSTS[-1]:
            continue
        # Лимиты запросов: повтор безопасен, VK ничего не создал.
        wait = RETRY_CODES.get(err.get("error_code", 0))
        if wait and _retries < 3:
            time.sleep(wait)
            return api(method, params, token, _retries + 1)
        return payload

    return payload


def explain_error(err: dict) -> str:
    code = err.get("error_code")
    hints = {
        5: "токен не принят. Ключ сообщества создан? Скопирован без пробелов? Отозван?",
        15: "у ключа нет права wall. Пересоздай ключ в настройках сообщества с галочками Управление + Стена (wall, photos, docs).",
        27: "VK не принимает этот тип ключа для метода. Ключ должен быть создан в НАСТРОЙКАХ СООБЩЕСТВА, а не в приложении.",
        1051: "тот же случай, что 27: нужен ключ доступа сообщества из его настроек.",
        214: "нет доступа к публикации: проверь owner_id (минус + id сообщества) и что ты админ.",
        219: "недавно уже публиковалась рекламная запись — подожди.",
        222: "ссылки в записи запрещены: у сообщества низкий траст либо ссылка в чёрном списке VK.",
        100: "неверный параметр запроса — смотри текст ошибки выше.",
    }
    msg = err.get("error_msg", "")
    hint = next((v for k, v in hints.items() if k == code), "")
    return f"VK API {code}: {msg}" + (f"\n→ {hint}" if hint else "")


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict):
    VK_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def community_id(raw: str) -> str:
    raw = str(raw).strip()
    if raw.lstrip("-").isdigit():
        return raw.lstrip("-")
    # screen_name → числовой id через утилиту resolveScreenName недоступен
    # ключу сообщества, поэтому просим числом и честно об этом говорим.
    die(f"VK_GROUP_ID должен быть числом, получено «{raw}». "
        "Числовой id виден в адресе управления сообществом: vk.com/groups?act=manage или "
        "в ссылке «Управление» (club<id>).")


def main():
    ap = argparse.ArgumentParser(description="Публикация статьи GEEKOVSKI во ВКонтакте")
    ap.add_argument("--slug", help="слаг статьи из content/posts (без .md)")
    ap.add_argument("--text-file", help="txt с готовым текстом поста (перебивает автогенерацию)")
    ap.add_argument("--post", action="store_true", help="реально отправить в VK")
    ap.add_argument("--dry-run", action="store_true", help="только показать пост и параметры")
    ap.add_argument("--publish-at", help='отложенная публикация, "2026-11-15 10:00" (МСК)')
    ap.add_argument("--url", help="переопределить ссылку-вложение")
    ap.add_argument("--owner", help="id сообщества (по умолчанию VK_GROUP_ID)")
    ap.add_argument("--token", help="ключ доступа (по умолчанию VK_GROUP_TOKEN)")
    ap.add_argument("--force", action="store_true", help="публиковать, даже если слаг уже в posted.json")
    ap.add_argument("--from-file", help="текст поста из файла, без обращения к content/posts")
    ap.add_argument("--photo", help="фото-вложение для поста (jpg/png); для ссылки строкой это обязательно")
    ap.add_argument("--id", dest="pid", help="идентификатор поста для дедупа, если он не из content/posts")
    args = ap.parse_args()

    # ключи профиля: в кроне окружение пустое, .env профиля само не подхватится
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import vk_smm
        vk_smm.load_profile_env()
    except Exception:
        pass

    if not args.slug and not args.from_file:
        die("нужен --slug или --from-file")

    url = args.url
    if args.slug:
        path = POSTS / f"{args.slug}.md"
        if not path.exists():
            die(f"нет файла статьи: {path}")
        meta = parse_frontmatter(path)
        url = url or article_url(meta)
        text = build_text(meta)
        if args.text_file:
            text = pathlib.Path(args.text_file).read_text(encoding="utf-8").strip()
        elif args.from_file:
            text = pathlib.Path(args.from_file).read_text(encoding="utf-8").strip()
        slug = meta["slug"]
    else:
        text = pathlib.Path(args.from_file).read_text(encoding="utf-8").strip()
        slug = args.pid or pathlib.Path(args.from_file).stem
        if not url:
            die("для --from-file нужен --url — иначе нечего прикладывать сниппетом")

    if not url:
        die("не удалось определить ссылку на статью")

    # Ссылка вложением больше не работает (ВК: link_photo_sizing_rule), поэтому
    # картинку грузим через сессию пользователя и она идёт attachment-ом, а URL —
    # отдельной строкой в тексте поста.
    photo = None
    web_fallback = False
    if args.photo:
        pth = pathlib.Path(args.photo).expanduser()
        if not pth.exists():
            die("нет файла фото: %s" % pth)
        if url not in text:
            text = text.rstrip() + "\n\n" + url
        sys.path.insert(0, str(ROOT / "tools"))
        import vk_session
        try:
            photo = vk_session.upload_wall_photo(pth, community_id(
                args.owner or os.environ.get("VK_GROUP_ID", "")), vk_session.token())
        except Exception as exc:
            # API-фото упирается в привязку токена к IP. Пока её нет — ставим
            # пост веб-клиентом сообщества: сессия в cookie, без токена и без привязки.
            sys.stderr.write("фото через API не ушло (%s) — ставлю пост веб-клиентом\n" % exc)
            photo = None
            web_fallback = True
    elif args.post:
        die("пост в ВК ставится только с фото: передай --photo (иначе ВК отбивает вложение-ссылку)")

    state = load_state()
    done = state.get(slug)
    if done and not args.force and not args.dry_run:
        die(f"«{slug}» уже опубликован {done.get('published_at')}: {done.get('vk_url', '')}\n"
            "нужно продублировать — добавь --force")

    params = {
        "owner_id": f"-{community_id(args.owner or os.environ.get('VK_GROUP_ID', ''))}"
        if (args.owner or os.environ.get("VK_GROUP_ID")) else None,
        "from_group": 1,
        "message": text,
        "attachments": photo or url,
        # guid одинаков для одной и той же статьи: повторный вызов в течение часа
        # VK отбросит сам, дубля на стене не будет.
        "guid": hashlib.md5(f"geekovski:{slug}:{url}".encode()).hexdigest(),
    }
    params = {k: v for k, v in params.items() if v is not None}

    if args.publish_at:
        try:
            when = datetime.strptime(args.publish_at, "%Y-%m-%d %H:%M")
        except ValueError:
            die('формат --publish-at: "2026-11-15 10:00"')
        ts = int(when.replace(tzinfo=timezone.utc).timestamp()) - 3 * 3600
        if ts <= time.time() + 300:
            die("--publish-at должно быть минимум на 5 минут в будущем")
        params["publish_date"] = ts

    print(f"— пост для ВК: {slug}")
    print(f"— ссылка-вложение: {url}")
    print(f"— длина текста: {len(text)} символов")
    if args.publish_at:
        print(f"— отложено на: {args.publish_at} МСК")
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60 + "\n")

    if args.dry_run or not args.post:
        print("dry-run: в VK ничего не отправлено. Для публикации добавь --post")
        return 0

    token = args.token or os.environ.get("VK_GROUP_TOKEN", "")
    if not token:
        die("нет токена: задай VK_GROUP_TOKEN в окружении или передай --token")
    if not params.get("owner_id"):
        die("нет id сообщества: задай VK_GROUP_ID или передай --owner")

    if photo is None and args.photo:
        sys.path.insert(0, str(ROOT / "tools"))
        import vk_session
        res = vk_session.post_text(text, community_id(params["owner_id"]))
        state[slug] = {"post_id": res["post_id"], "owner_id": "-" + str(params["owner_id"]),
                       "vk_url": res["vk_url"], "url": url,
                       "published_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "scheduled_for": args.publish_at, "text": text,
                       "via": "web"}
        save_state(state)
        print("Опубликовано (веб-клиент, без фото): " + res["vk_url"])
        return 0

    payload = api("wall.post", params, token)
    if "error" in payload:
        die(explain_error(payload["error"]))
    post_id = payload["response"]["post_id"]
    vk_url = f"https://vk.com/wall{params['owner_id']}_{post_id}"
    state[slug] = {
        "post_id": post_id,
        "owner_id": params["owner_id"],
        "vk_url": vk_url,
        "url": url,
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scheduled_for": args.publish_at,
        "text": text,
    }
    save_state(state)
    print(("Отложено: " if args.publish_at else "Опубликовано: ") + vk_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
