#!/usr/bin/env python3
"""SMM-контур сообщества ВКонтакте: снимки, отчёты, комментарии, события.

Публикация живёт отдельно в tools/vk_publish.py (wall.post + отложка).
Здесь — вторая половина работы: что стало с тем, что опубликовано.

Модель доступа (проверено по справке dev.vk.com, ноябрь 2026):

    VK_SERVICE_TOKEN — сервисный ключ Standalone-приложения.
        Читает публичное: wall.get, wall.getComments, groups.getById.
        Писать не может.
    VK_GROUP_TOKEN — ключ из настроек сообщества (права wall, photos,
        docs, messages, manage). Пишет от имени сообщества, отвечает в
        комментариях, читает Long Poll (groups.getLongPollServer), но
        стену не читает и фото не грузит.
    stats.get — только ключ пользователя, а он с 25.06.2024 не выдаётся
        обычным способом. Охваты/источники берём глазами в браузере,
        всё остальное — здесь.

Команды:
    python3 tools/vk_smm.py check                 # какие ключи живы и что умеют
    python3 tools/vk_smm.py audit                 # снимок: подписчики + посты
    python3 tools/vk_smm.py report --days 7       # отчёт с дельтами (markdown)
    python3 tools/vk_smm.py comments --new        # новые комментарии с прошлого раза
    python3 tools/vk_smm.py reply --post-id 12 --text "..."          # черновик ответа
    python3 tools/vk_smm.py reply --post-id 12 --text "..." --send   # отправить
    python3 tools/vk_smm.py poll --wait 25        # события Long Poll с прошлого ts
    python3 tools/vk_smm.py members --days 30     # динамика подписок по снимкам
"""

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import NoReturn

ROOT = pathlib.Path(__file__).resolve().parents[1]
VK_DIR = ROOT / "content" / "vk"
STATE_DIR = VK_DIR / "state"
SNAPSHOTS = STATE_DIR / "snapshots.jsonl"
SEEN_COMMENTS = STATE_DIR / "comments.json"
LONGPOLL_STATE = STATE_DIR / "longpoll.json"
REPLY_LOG = STATE_DIR / "replies.jsonl"

API_HOSTS = ("https://api.vk.ru/method/", "https://api.vk.com/method/")
API_V = "5.199"
RETRY_CODES = {6: 3, 9: 60, 10: 60}

# Что каждый тип ключа умеет — для команды check и для внятных ошибок.
CAPABILITIES = [
    ("wall.get", "service", "чтение стены и метрик постов"),
    ("wall.getComments", "service", "чтение комментариев"),
    ("groups.getById", "service", "подписчики, счётчики, описание"),
    ("wall.post", "group", "публикация и отложка"),
    ("wall.createComment", "group", "ответ подписчику от имени сообщества"),
    ("wall.deleteComment", "group", "удаление комментария"),
    ("groups.getLongPollServer", "group", "живые события: комменты, подписки, ЛС"),
    ("messages.getConversations", "group", "личные сообщения сообщества"),
    ("stats.get", "user", "охваты, источники, демография — НЕДОСТУПНО"),
]


def die(msg, code=1) -> NoReturn:
    sys.stdout.flush()
    print("✗ " + msg, file=sys.stderr)
    sys.exit(code)


def load_profile_env():
    """Крон запускает скрипт в чистом окружении — добираем ключи из профиля."""
    path = pathlib.Path.home() / ".hermes" / "profiles" / "geekovski" / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and not os.environ.get(k):
            os.environ[k] = v


def env(name):
    return (os.environ.get(name) or "").strip()


def group_id():
    raw = env("VK_GROUP_ID").lstrip("-")
    if not raw.isdigit():
        die("нет VK_GROUP_ID: нужен числовой id сообщества (club<id> в адресе), "
            "short name API здесь не принимает")
    return raw


# ---------------------------------------------------------------- API


def api(method, params, token):
    data = dict(params)
    data["v"] = API_V
    body = urllib.parse.urlencode(data).encode()
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "geekovski-smm/1.0 (+https://geekovski.ru)",
    }
    payload = {"error": {"error_code": -1, "error_msg": "запрос не выполнен"}}

    for host in API_HOSTS:
        attempt = 0
        for attempt in range(3):
            req = urllib.request.Request(host + method, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    payload = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                raw = e.read().decode(errors="ignore")
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"error": {"error_code": e.code, "error_msg": raw[:200]}}
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                payload = {"error": {"error_code": -1, "error_msg": "сеть: %s" % e}}
            break

        err = payload.get("error", {})
        if err.get("error_code") == 5 and host is not API_HOSTS[-1]:
            continue
        wait = RETRY_CODES.get(err.get("error_code", 0))
        if wait and attempt < 3:
            time.sleep(wait)
            return api(method, params, token)
        return payload
    return payload


HINTS = {
    5: "ключ не принят: неверный, отозван или скопирован с пробелом",
    6: "слишком много запросов в секунду — пауза и повтор",
    9: "flood control — подождать минутами",
    15: "у ключа нет нужного права (wall / photos / docs / messages). Если это wall.get "
        "с сервисным ключом — сообщество закрытое: ВК отдаёт стену только участникам, "
        "нужно сделать сообщество открытым",
    27: "не тот тип ключа: этому методу нужен сервисный ключ приложения",
    100: "неверный параметр — читай текст ошибки",
    214: "нет доступа: проверь owner_id со знаком минус и права админа",
    200: "нет доступа к объекту (сообщество закрыто или удалено)",
}


def explain(err):
    code = err.get("error_code")
    out = "VK API %s: %s" % (code, err.get("error_msg", ""))
    if code in HINTS:
        out += "\n→ " + HINTS[code]
    return out


def call(method, params, token, what=""):
    payload = api(method, params, token)
    if "error" in payload:
        die(explain(payload["error"]) + ("\n  метод: " + method + (" — " + what if what else "")))
    return payload["response"]


# ---------------------------------------------------------------- состояние


def ensure_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def write_json(path, data):
    ensure_state()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshots():
    if not SNAPSHOTS.exists():
        return []
    out = []
    for line in SNAPSHOTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def append_snapshot(snap):
    ensure_state()
    with SNAPSHOTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- сбор данных


def fetch_group():
    """Число подписчиков и счётчики. Читается сервисным ключом."""
    token = env("VK_SERVICE_TOKEN") or env("VK_GROUP_TOKEN")
    resp = call("groups.getById", {
        "group_id": group_id(),
        "fields": "members_count,counters,description,status",
    }, token, "подписчики")
    if isinstance(resp, dict) and resp.get("groups"):
        item = resp["groups"][0]
    else:
        item = resp[0]
    counters = item.get("counters") or {}
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "screen_name": item.get("screen_name"),
        # 0 — открытое, 1 — закрытое (по заявке), 2 — частное (только для участников).
        # Для закрытого ВК не отдаёт стену даже сервисному ключу: ошибка 15.
        "is_closed": item.get("is_closed"),
        "members": item.get("members_count") or counters.get("members"),
        "photos": counters.get("photos"),
        "videos": counters.get("videos"),
        "topics": counters.get("topics"),
    }


def fetch_posts(limit=30):
    """Посты с реакциями. wall.get требует сервисный ключ, ключ сообщества тут не работает."""
    token = env("VK_SERVICE_TOKEN")
    if not token:
        die("для чтения стены нужен VK_SERVICE_TOKEN (сервисный ключ Standalone-приложения): "
            "ключ сообщества стену не читает")
    resp = call("wall.get", {
        "owner_id": "-" + group_id(),
        "count": limit,
        "filter": "all",
    }, token, "стена")
    posts = []
    for p in resp.get("items", []):
        likes = (p.get("likes") or {}).get("count", 0)
        comments = (p.get("comments") or {}).get("count", 0)
        reposts = (p.get("reposts") or {}).get("count", 0)
        views = (p.get("views") or {}).get("count")
        posts.append({
            "id": p.get("id"),
            "date": p.get("date"),
            "text": (p.get("text") or "")[:120].replace("\n", " "),
            "likes": likes,
            "comments": comments,
            "reposts": reposts,
            "views": views,
            "pinned": bool(p.get("is_pinned")),
            "url": "https://vk.com/wall-%s_%s" % (group_id(), p.get("id")),
            "engagement": likes + comments + reposts,
        })
    return posts


def fetch_comments(post_id, count=100):
    token = env("VK_SERVICE_TOKEN")
    if not token:
        die("для чтения комментариев нужен VK_SERVICE_TOKEN")
    resp = call("wall.getComments", {
        "owner_id": "-" + group_id(),
        "post_id": post_id,
        "count": count,
        "sort": "desc",
        "extended": 0,
        "need_likes": 1,
    }, token, "комментарии поста %s" % post_id)
    out = []
    for c in resp.get("items", []):
        out.append({
            "id": c.get("id"),
            "post_id": post_id,
            "from_id": c.get("from_id"),
            "date": c.get("date"),
            "text": (c.get("text") or "").replace("\n", " "),
            "likes": (c.get("likes") or {}).get("count", 0),
            "reply_to_comment": c.get("reply_to_comment"),
            "reply_to_user": c.get("reply_to_user"),
            "thread": (c.get("thread") or {}).get("count", 0),
            "from_group": str(c.get("from_id")) == ("-" + group_id()),
        })
    return out


# ---------------------------------------------------------------- отрисовка


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else "—"


def er(post, members):
    base = post.get("views") or members
    if not base:
        return None
    return 100.0 * post["engagement"] / base


def render_snapshot(snap, prev=None):
    lines = []
    members = snap["group"].get("members")
    head = "**%s** — подписчиков: %s" % (snap["group"].get("name") or "сообщество", members)
    if prev and prev.get("group", {}).get("members") and members:
        diff = members - prev["group"]["members"]
        head += " (%+d за %s)" % (diff, days_between(prev["ts"], snap["ts"]))
    lines.append(head)

    posts = snap.get("posts", [])
    if posts:
        total = sum(p["engagement"] for p in posts)
        lines.append("Постов в снимке: %d, реакций суммарно: %d" % (len(posts), total))
        lines.append("")
        lines.append("| пост | дата | ♥ | 💬 | ↗ | охват | ER |")
        lines.append("|---|---|---|---|---|---|---|")
        for p in posts[:12]:
            e = er(p, members)
            lines.append("| [%s](%s) | %s | %d | %d | %d | %s | %s |" % (
                (p["text"][:46] + "…") if len(p["text"]) > 46 else (p["text"] or "—"),
                p["url"], fmt_ts(p["date"]), p["likes"], p["comments"], p["reposts"],
                p["views"] if p["views"] is not None else "—",
                ("%.1f%%" % e) if e is not None else "—",
            ))
    return "\n".join(lines)


def days_between(a, b):
    try:
        d = (b - a) / 86400.0
    except TypeError:
        return "?"
    if d < 1:
        return "%.1f ч" % ((b - a) / 3600.0)
    return "%.1f дн" % d


def pick_prev(snap_list, days):
    """Ближайший снимок старше N дней назад (или самый старый, если история короче)."""
    if not snap_list:
        return None
    cutoff = time.time() - days * 86400
    older = [s for s in snap_list if s["ts"] <= cutoff]
    return older[-1] if older else snap_list[0]


def render_report(cur, prev, days):
    lines = ["# ВК — отчёт за %d дн." % days, ""]
    g, pg = cur["group"], (prev or {}).get("group", {})
    members = g.get("members")
    delta = (members - pg["members"]) if (pg.get("members") and members) else None
    lines.append("**Подписчики:** %s%s" % (
        members, (" (%+d с %s)" % (delta, fmt_ts(prev["ts"]))) if delta is not None else ""))
    lines.append("")

    if prev:
        new_posts = [p for p in cur.get("posts", []) if p["date"] > prev["ts"]]
        old = {p["id"]: p for p in prev.get("posts", [])}
        lines.append("**Постов за период:** %d" % len(new_posts))
        growth = 0
        for p in cur.get("posts", []):
            if p["id"] in old:
                growth += p["engagement"] - old[p["id"]]["engagement"]
        lines.append("**Реакций накопилось** на старых постах: %+d" % growth)
        if new_posts:
            agg = sum(p["engagement"] for p in new_posts)
            lines.append("**Реакций на новых постах:** %d" % agg)
        best = sorted(cur.get("posts", []), key=lambda p: p["engagement"], reverse=True)[:3]
        if best:
            lines.append("")
            lines.append("**Топ по вовлечённости:**")
            for p in best:
                lines.append("- %s — %d реакций, %s просмотров — %s" % (
                    (p["text"][:60] or "без текста"), p["engagement"],
                    p["views"] if p["views"] is not None else "—", p["url"]))
        quiet = [p for p in cur.get("posts", []) if p["date"] > prev["ts"] and p["engagement"] == 0]
        if quiet:
            lines.append("")
            lines.append("**Ноль реакций:** %s" % ", ".join(p["url"] for p in quiet))
    else:
        lines.append("Предыдущего снимка нет — это первый, дельт пока не будет.")
    return "\n".join(lines)


# ---------------------------------------------------------------- команды


def cmd_check(args):
    gid = env("VK_GROUP_ID")
    service = env("VK_SERVICE_TOKEN")
    grp = env("VK_GROUP_TOKEN")
    print("VK_GROUP_ID: %s" % (gid or "— нет"))
    print("VK_SERVICE_TOKEN: %s" % ("задан" if service else "— нет"))
    print("VK_GROUP_TOKEN: %s" % ("задан" if grp else "— нет"))
    print("")
    print("| метод | ключ | назначение | статус |")
    print("|---|---|---|---|")
    checks = [
        ("groups.getById", {"group_id": gid or "1", "fields": "members_count"}, service),
        ("wall.get", {"owner_id": "-" + (gid or "1"), "count": 1}, service),
        ("groups.getLongPollServer", {"group_id": gid or "1"}, grp),
    ]
    results = {}
    for method, params, token in checks:
        if not token:
            results[method] = "нет ключа"
            continue
        payload = api(method, params, token)
        if "error" in payload:
            results[method] = "✗ " + str(payload["error"].get("error_code"))
        else:
            results[method] = "✓"
    for method, kind, why in CAPABILITIES:
        status = results.get(method)
        if status is None:
            status = "не проверяю" if kind == "user" else "проверяется по факту вызова"
        print("| %s | %s | %s | %s |" % (method, kind, why, status))
    return 0


def cmd_audit(args):
    g = fetch_group()
    if g.get("is_closed"):
        print("! сообщество закрытое (is_closed=%s): стена и комментарии доступны только "
              "участникам, поэтому аналитика не читается. Открыть: Управление → Настройки → "
              "Основная информация → Тип сообщества → Открытое." % g["is_closed"])
    posts = fetch_posts(args.limit)
    snap = {"ts": int(time.time()), "group": g, "posts": posts}
    prev = snapshots()[-1] if snapshots() else None
    append_snapshot(snap)
    print(render_snapshot(snap, prev))
    print("")
    print("снимок записан: %s (всего снимков: %d)" % (SNAPSHOTS.relative_to(ROOT), len(snapshots())))
    return 0


def cmd_report(args):
    g = fetch_group()
    posts = fetch_posts(args.limit)
    cur = {"ts": int(time.time()), "group": g, "posts": posts}
    prev = pick_prev(snapshots(), args.days)
    print(render_report(cur, prev, args.days))
    return 0


def cmd_members(args):
    snaps = snapshots()
    if not snaps:
        die("снимков нет: сначала запусти audit")
    cutoff = time.time() - args.days * 86400
    window = [s for s in snaps if s["ts"] >= cutoff] or snaps[-2:]
    print("| когда | подписчиков | дельта |")
    print("|---|---|---|")
    prev = None
    for s in window:
        m = s["group"].get("members")
        d = "" if prev is None or m is None else "%+d" % (m - prev)
        print("| %s | %s | %s |" % (fmt_ts(s["ts"]), m, d))
        prev = m if m is not None else prev
    return 0


def cmd_comments(args):
    state = read_json(SEEN_COMMENTS, {"seen": []})
    seen = set(state.get("seen", []))
    posts = [args.post_id] if args.post_id else [p["id"] for p in fetch_posts(5)]
    fresh = []
    for pid in posts:
        for c in fetch_comments(pid):
            key = "%s_%s" % (pid, c["id"])
            c["key"] = key
            if key not in seen:
                fresh.append(c)
    fresh.sort(key=lambda c: c["date"] or 0)
    if not fresh:
        print("новых комментариев нет (проверено постов: %d)" % len(posts))
        return 0
    print("новых комментариев: %d" % len(fresh))
    print("")
    for c in fresh:
        flag = "← от сообщества" if c["from_group"] else ""
        print("- %s [%s] %s: %s %s" % (
            fmt_ts(c["date"]), c["key"], c["from_id"], c["text"][:200], flag))
        print("  https://vk.com/wall-%s_%s?reply=%s" % (group_id(), c["post_id"], c["id"]))
    if args.mark_seen:
        seen.update(c["key"] for c in fresh)
        write_json(SEEN_COMMENTS, {"seen": sorted(seen), "updated": int(time.time())})
        print("\nотмечено прочитанным: %d" % len(fresh))
    return 0


def cmd_reply(args):
    text = args.text.strip()
    if not text:
        die("пустой текст ответа")
    if not args.send:
        print("черновик ответа в пост %s:\n" % args.post_id)
        print(text)
        print("\nэто черновик: чтобы отправить от имени сообщества — добавь --send")
        return 0
    token = env("VK_GROUP_TOKEN")
    if not token:
        die("для ответа нужен VK_GROUP_TOKEN")
    params = {"owner_id": "-" + group_id(), "post_id": args.post_id, "message": text,
              "from_group": 1}
    if args.comment_id:
        params["reply_to_comment"] = args.comment_id
    resp = call("wall.createComment", params, token, "ответ в комментариях")
    cid = resp.get("comment_id")
    ensure_state()
    with REPLY_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "post_id": args.post_id,
                            "comment_id": cid, "text": text}, ensure_ascii=False) + "\n")
    print("ответ отправлен: https://vk.com/wall-%s_%s?reply=%s" % (group_id(), args.post_id, cid))
    return 0


def cmd_poll(args):
    token = env("VK_GROUP_TOKEN")
    if not token:
        die("Long Poll работает только с ключом сообщества (VK_GROUP_TOKEN)")
    state = read_json(LONGPOLL_STATE, {})
    server = call("groups.getLongPollServer", {"group_id": group_id()}, token, "Long Poll")
    ts = state.get("ts") or server["ts"]
    url = "%s?act=a_check&key=%s&ts=%s&wait=%d&mode=2&version=3" % (
        server["server"], server["key"], ts, args.wait)
    try:
        with urllib.request.urlopen(url, timeout=args.wait + 30) as r:
            payload = json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        die("Long Poll не ответил: %s" % e)
    if "failed" in payload:
        # 1 — устаревший ts, 2/3 — пересоздать ключ соединения: сбрасываем ts.
        write_json(LONGPOLL_STATE, {})
        die("Long Poll failed=%s — состояние сброшено, следующий запуск начнёт заново"
            % payload["failed"])
    updates = payload.get("updates", [])
    write_json(LONGPOLL_STATE, {"ts": payload.get("ts"), "updated": int(time.time())})
    if not updates:
        print("событий нет (ts=%s)" % payload.get("ts"))
        return 0
    names = {1: "замена флагов", 2: "новое значение флагов", 3: "сброс флагов",
             4: "новое сообщение", 5: "правка сообщения", 6: "прочтение входящих",
             7: "прочтение исходящих", 8: "друг в сети", 9: "удаление друга",
             10: "сброс чата", 11: "удаление сообщения", 61: "ввод текста",
             62: "ответ в диалоге",
             100: "новый пост на стене", 101: "правка поста", 102: "удаление поста",
             103: "восстановление поста", 104: "новый комментарий к посту",
             105: "правка комментария", 106: "удаление комментария",
             107: "восстановление комментария", 108: "новый ответ в комментариях",
             109: "правка ответа", 110: "удаление ответа",
             111: "восстановление ответа", 112: "новый участник",
             113: "участник покинул сообщество"}
    print("событий: %d" % len(updates))
    for u in updates:
        print("- %s: %s" % (names.get(u.get("type"), "тип %s" % u.get("type")),
                            json.dumps({k: v for k, v in u.items() if k not in
                                        ("type", "object")}, ensure_ascii=False)[:300]))
    return 0


def main():
    load_profile_env()
    ap = argparse.ArgumentParser(description="SMM-контур сообщества ВК")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("check", help="проверить ключи и их права")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("audit", help="снять снимок сообщества и постов")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("report", help="отчёт с дельтами")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("members", help="динамика подписчиков по снимкам")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_members)

    p = sub.add_parser("comments", help="комментарии к последним постам")
    p.add_argument("--post-id", type=int)
    p.add_argument("--new", action="store_true", help="только невиденные раньше")
    p.add_argument("--mark-seen", action="store_true")
    p.set_defaults(func=cmd_comments)

    p = sub.add_parser("reply", help="ответ в комментариях")
    p.add_argument("--post-id", type=int, required=True)
    p.add_argument("--comment-id", type=int)
    p.add_argument("--text", required=True)
    p.add_argument("--send", action="store_true", help="реально отправить (по умолчанию черновик)")
    p.set_defaults(func=cmd_reply)

    p = sub.add_parser("poll", help="события Long Poll с прошлого запуска")
    p.add_argument("--wait", type=int, default=25)
    p.set_defaults(func=cmd_poll)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
