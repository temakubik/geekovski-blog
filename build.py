#!/usr/bin/env python3
"""GEEKOVSKI static blog generator.

Читает content/posts/*.md, собирает статический сайт в docs/.
Только стандартная библиотека — ничего устанавливать не нужно.

  python3 build.py                 # собрать сайт из content/
  python3 build.py --theme magazine --out /tmp/preview
"""
import argparse
import collections
import hashlib
import html
import json
import os
import re
import shutil
import struct
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dzen_feed import adapt_html as dzen_html

ROOT = Path(__file__).resolve().parent
SITE = {
    "title": "GEEKOVSKI",
    "tagline": "Технологии, игры и кино без маркетингового сиропа",
    "url": "https://geekovski.ru",
    "lang": "ru",
    "author": "GEEKOVSKI",
    # сообщество ВК (screen_name из groups.getById): ссылка стоит в контактах
    # внизу сайта и в sameAs организации — поисковики склеивают канал и группу
    "vk": "https://vk.com/geekovskiread",
}
CATS = [
    ("xbox", "Xbox"),
    ("switch", "Nintendo Switch"),
    ("playstation", "PlayStation"),
    ("pc", "PC-игры"),
    ("vr", "VR"),
    ("gadgets", "Гаджеты"),
    ("kino", "Кино"),
    ("serialy", "Сериалы"),
    ("ai", "AI"),
]
CAT_NAME = dict(CATS)
CAT_DESCRIPTION = {
    "xbox": "Новости Xbox, Game Pass и студий Microsoft. Релизы, обновления консолей и изменения в подписке.",
    "switch": "Игры для Nintendo Switch и Switch 2, обновления консолей и новости Nintendo.",
    "playstation": "Игры для PlayStation, обновления PS5 и PS5 Pro, новости студий Sony и подписки PS Plus.",
    "pc": "Новости PC-игр, Steam и игровых студий. Релизы, обновления и системные требования.",
    "vr": "Игры в виртуальной реальности, шлемы VR и устройства для смешанной реальности.",
    "gadgets": "Смартфоны, портативные консоли и другая техника. Характеристики, цены и даты выхода.",
    "kino": "Трейлеры, премьеры, кассовые сборы и новости о том, как снимают кино.",
    "serialy": "Премьеры сериалов, новые сезоны и новости стриминговых сервисов.",
    "ai": "Новости об искусственном интеллекте, языковых моделях и том, как ИИ меняет игры и технику.",
}
# старые слаги заметок → новые рубрики
CAT_ALIAS = {"igry": "switch", "techno": "ai"}


# ---------- front matter ----------

def parse_post(path: Path):
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        for line in fm.strip().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    slug = meta.get("slug") or path.stem
    cat = meta.get("category", "ai").strip().lower()
    cat = CAT_ALIAS.get(cat, cat)
    if cat not in CAT_NAME:
        cat = "ai"
    date = datetime.strptime(meta.get("date", "2026-01-01 00:00"), "%Y-%m-%d %H:%M")
    # updated: — необязательная дата правки. Если её нет, dateModified = date:
    # подставлять mtime файла нельзя, иначе пересборка на другой машине «омолодит» статью.
    updated = date
    if meta.get("updated"):
        try:
            updated = datetime.strptime(meta["updated"], "%Y-%m-%d %H:%M")
        except ValueError:
            updated = date
    sources = []
    for line in meta.get("sources", "").split(";"):
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            name, url = line.rsplit("|", 1)
            sources.append({"name": name.strip(), "url": url.strip()})
        else:
            sources.append({"name": line, "url": ""})
    kind = meta.get("kind", "post").strip().lower()
    if kind not in ("post", "digest", "calendar", "game", "film", "series", "gadget"):
        kind = "post"
    # tldr: пункт | пункт — выжимка для блока «Коротко» в начале материала
    tldr = [x.strip() for x in meta.get("tldr", "").split("|") if x.strip()]
    items, cur = [], None
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        # «- category: switch» открывает новость, «title: …» / «summary: …» её дополняют
        m = re.match(r"^(?:-\s+)?([a-z_]+):\s*(.*)$", s)
        allowed = ("category", "title", "summary", "source", "platforms", "kind_note",
                   "date", "where", "day", "cover", "slug")
        if not (m and m.group(1) in allowed):
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "category" and kind == "calendar":
            cur = {"category": val.lower(), "title": "", "summary": "", "source": "",
                   "platforms": "", "kind_note": "", "date": "", "where": ""}
            items.append(cur)
        elif key == "category":
            cur = {"category": val.lower(), "title": "", "summary": "", "source": ""}
            items.append(cur)
        elif kind == "calendar" and cur is not None:
            cur[key] = val   # date / platforms / kind_note / where / title / summary / source
        elif kind == "calendar" and cur is not None and key == "date":
            cur["date"] = val
        elif kind == "calendar" and cur is not None and key in ("platforms", "kind_note", "where"):
            cur[key] = val
        elif cur is not None:
            cur[key] = val
    if kind not in ("digest", "calendar"):
        items, body_lines = [], body.splitlines()
    else:
        body_lines = []
    return {
        "items": items,
        "tldr": tldr,
        "kind": kind,
        "slug": slug,
        "title": meta.get("title", "Без заголовка"),
        "date": date,
        "updated": updated,
        "category": cat,
        "summary": meta.get("summary", ""),
        "cover": meta.get("cover", ""),
        "pin": meta.get("pin", ""),
        "credit": meta.get("credit", ""),
        "body": "\n".join(body_lines).strip(),
        "sources": sources,
        "draft": meta.get("draft", "false").lower() == "true",
        "file": path,
        "meta": meta,
    }


# ---------- markdown ----------

NBSP = "\u00a0"

# Короткие слова, которые не должны висеть в конце строки: «в», «на», «и» и т. п.
_SHORT_WORDS = ("в|во|на|и|а|но|с|со|к|ко|по|у|о|об|от|до|из|за|для|при|не|ни|"
                "же|ли|бы|или|под|над|без|про|через|после|перед|между|что|как|"
                "то|так|все|всё|это|их|его|её|им|ей|мне|мы|вы|он|она|они")


def typo_text(t: str) -> str:
    """Русская типографика прямо в тексте публикации.

    Что делает и зачем:
    - дефис между словами превращает в тире с неразрывным пробелом ПЕРЕД ним:
      «слово — слово». Тире никогда не начинает строку, а висячий дефис не рвёт вёрстку;
    - приклеивает короткие предлоги и союзы («в», «на», «и») к следующему слову
      неразрывным пробелом — именно из-за них в тексте появлялись строки из одного слова;
    - «5 ноября», «212 ГБ», «12 %» держит вместе: число не отрывается от единицы;
    - «т. д.», «т. п.» приводит к одному виду;
    - три точки — в один символ многоточия.
    """
    if not t:
        return t
    t = re.sub(r"[ \t]{2,}", " ", t)
    # тире: только когда пробелы с двух сторон. Дефис в «--theme» или «file-name»
    # иначе превращался в тире и ломал код в статьях
    t = re.sub(r"[ \t]+[-–—][ \t]+", NBSP + "— ", t)
    # короткие слова приклеиваются к следующему слову
    t = re.sub(r"(?<![\w" + NBSP + r"])(" + _SHORT_WORDS + r")\s+", lambda m: m.group(1) + NBSP, t)
    # число + единица/слово/валюта
    t = re.sub(r"(\d)\s+(?=[\wА-Яа-яЁё$€₽])", lambda m: m.group(1) + NBSP, t)
    t = re.sub(r"(\d)\s*([%°])", lambda m: m.group(1) + NBSP + m.group(2), t)
    t = re.sub(r"\bт\.\s*д\.", "т." + NBSP + "д.", t)
    t = re.sub(r"\bт\.\s*п\.", "т." + NBSP + "п.", t)
    t = t.replace("...", "…")
    return t


def typo_html(fragment: str) -> str:
    """Типографика только по текстовым узлам: атрибуты, теги и <code> не трогаем."""
    parts = re.split(r"(<[^>]*>)", fragment)
    in_code = False
    for i, part in enumerate(parts):
        if part.startswith("<"):
            low = part.lower()
            if low.startswith("<code"):
                in_code = True
            elif low.startswith("</code"):
                in_code = False
            continue
        if part and not in_code:
            parts[i] = typo_text(part)
    return "".join(parts)


def md_inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    # ссылки: абсолютные И относительные (/rss.xml, /about.html) — на страницах сайта
    # используются оба вида, и раньше относительные оставались сырым markdown
    def _link(m):
        label, href = m.group(1), m.group(2)
        cls = ' class="tlink"' if href.startswith("/titles/") else ""
        return '<a%s href="%s">%s</a>' % (cls, href, label)
    text = re.sub(r"\[([^\]]+)\]\(((?:https?://|/)[^)\s]+)\)", _link, text)
    return typo_html(text)


def _table_html(head, rows, aligns):
    """Таблица из markdown. Первая строка — заголовок, <th> внутри <thead>.

    ВАЖНО: таблица вставляется в шаблон через .format() только в других местах;
    здесь обычная склейка, поэтому скобки не удваиваем.
    """
    def cell(tag, txt, idx):
        al = aligns[idx] if idx < len(aligns) else "left"
        return '<%s style="text-align:%s">%s</%s>' % (tag, al, md_inline(txt), tag)
    th = "".join(cell("th", c, k) for k, c in enumerate(head))
    tb = ""
    for r in rows:
        tds = "".join(cell("td", c, k) for k, c in enumerate(r))
        tb += "<tr>%s</tr>" % tds
    return ('<div class="table-wrap"><table>'
            '<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, tb))


def md(text: str) -> str:
    out, buf, mode = [], [], None
    def flush():
        nonlocal buf, mode
        if not buf:
            mode = None
            return
        chunk = "\n".join(buf).strip()
        if mode == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % md_inline(x) for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join("<li>%s</li>" % md_inline(re.sub(r"^\d+\.\s*", "", x)) for x in buf) + "</ol>")
        elif mode == "quote":
            out.append("<blockquote><p>%s</p></blockquote>" % md_inline(chunk))
        else:
            out.append("<p>%s</p>" % md_inline(chunk))
        buf, mode = [], None

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.rstrip()
        # ТАБЛИЦА: строка «|…|», затем разделитель «|---|:--:|». Без этой ветки
        # трубы печатались в тексте как «| Издание | Первое место |», и автор
        # видел «таблица отображается некорректно» вместо самой таблицы.
        if s.strip().startswith("|") and i + 1 < len(lines) and re.match(
                r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            flush()
            head = [c.strip() for c in s.strip().strip("|").split("|")]
            aligns = []
            for c in lines[i + 1].strip().strip("|").split("|"):
                c = c.strip()
                aligns.append("center" if c.startswith(":") and c.endswith(":")
                              else "right" if c.endswith(":") else "left")
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            out.append(_table_html(head, rows, aligns))
            i = j
            continue
        i += 1
        if not s.strip():
            flush()
            continue
        mi = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", s)
        if mi:
            flush()
            alt, src = mi.group(1), mi.group(2)
            # image_tag подставляет width/height из файла: без них картинка
            # занимает нулевую высоту и текст прыгает, когда она догрузится
            out.append('<figure class="post__fig">%s</figure>' % image_tag(src, alt))
            continue
        m = re.match(r"^(#{2,4})\s+(.*)$", s)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, md_inline(m.group(2)), lvl))
            continue
        if s.startswith("- ") or s.startswith("* "):
            if mode not in (None, "ul"):
                flush()
            mode = "ul"; buf.append(s[2:].strip()); continue
        if re.match(r"^\d+\.\s", s):
            if mode not in (None, "ol"):
                flush()
            mode = "ol"; buf.append(s); continue
        if s.startswith("> "):
            if mode != "quote":
                flush()
            mode = "quote"; buf.append(s[2:].strip()); continue
        if mode in ("ul", "ol", "quote"):
            buf.append(s.strip()); continue
        buf.append(s)
    flush()
    return "\n".join(out)


def plain(text: str, n: int = 240) -> str:
    t = re.sub(r"[#*`>\-]", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n].rstrip() + ("…" if len(t) > n else "")


# ---------- templates ----------

NAV_COUNTS = {"posts": 0, "digests": 0, "rubrics": 0, "calendars": 0, "titles": 0}
open_rubrics = {}   # заполняется в build(): слаг -> число материалов
CATEGORIES_PATH = "/categories/"
SIDEBAR_ICONS = {
    "blog": '<rect x="4" y="3" width="16" height="18"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "categories": '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    "authors": '<circle cx="12" cy="7" r="3"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
    "calendar": '<rect x="4" y="5" width="16" height="15"/><path d="M8 3v4m8-4v4M4 10h16m-12 4h2m4 0h2"/>',
    "digests": '<path d="M7 7h13v13H7zM4 17V4h13m-7 7h7m-7 4h7"/>',
    "catalog": '<path d="M3 5h7v15H3zM14 5h4l3 14-4 1zM6 8h2m-2 4h2"/>',
    "collapse": '<path d="M15 6l-6 6 6 6"/>',
}


def sidebar_icon(name):
    return ('<svg class="sidebar-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" '
            'stroke="currentColor" stroke-width="1.6" aria-hidden="true" focusable="false">'
            f'{SIDEBAR_ICONS[name]}</svg>')


def nav(theme, canonical):
    if theme == "editorial":
        links = [("/", "Блог", NAV_COUNTS["posts"], "blog"),
                 (CATEGORIES_PATH, "Категории", len(CATS), "categories"),
                 ("/avtory/", "Авторы", None, "authors"), ("/calendar/", "Календарь", None, "calendar"),
                 ("/digests/", "Дайджесты", NAV_COUNTS["digests"], "digests"),
                 (CATALOG_PATH, "Каталог", NAV_COUNTS["titles"], "catalog")]
        route = urllib.parse.urlsplit(canonical or "").path
        section = next((path for path, *_ in links[1:] if route.startswith(path)), "/")
        if route.strip("/") in CAT_NAME:
            section = CATEGORIES_PATH
        return "".join(nav_link(path, label, canonical, " nav__link--active" if path == section and route else "",
                                count, icon=icon) for path, label, count, icon in links)
    c = dict(NAV_COUNTS)
    c["rubrics"] = sum(1 for k, _ in CATS if open_rubrics.get(k))
    return ('<a class="nav__link nav__link--blog" href="/">Блог<span class="nav__num">(%d)</span></a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<a class="nav__link nav__link--digests" href="/digests/">Дайджесты<span class="nav__num">(%d)</span></a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<a class="nav__link nav__link--cal" href="/calendar/">Календарь<span class="nav__num">(%d)</span></a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<a class="nav__link" href="/titles/">Каталог</a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<a class="nav__link nav__link--authors" href="/avtory/">Авторы</a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<details class="nav__rubrics"><summary class="nav__link">Рубрики<span class="nav__num">(%d)</span></summary>'
            '<div class="nav__categories">'
            % (c["posts"], c["digests"], c["calendars"], c["rubrics"])
            + "".join('<a class="nav__link nav__link--sm" href="/{slug}/">{name}</a>'.format(slug=k, name=n)
                      for k, n in CATS) + '</div></details>')


def nav_link(path, label, canonical, modifier="", count=None, icon=None):
    current = ' aria-current="page"' if canonical == SITE["url"] + path else ""
    title = f' title="{html.escape(label)}"' if icon else ""
    caption = f'{sidebar_icon(icon)}<span class="nav__label">{label}</span>' if icon else label
    number = f' <span class="nav__count">{count}</span>' if count is not None else ""
    return f'<a class="nav__link{modifier}" href="{path}"{current}{title}>{caption}{number}</a>'


PAGE = """<!DOCTYPE html>
<html lang="ru" data-theme="{theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="{robots}">
{canonical}
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="GEEKOVSKI">
<meta property="og:locale" content="ru_RU">
{og_url}
{og_image_meta}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
{article_meta}
<!--  — бренд-набор 2026-11-13: браузеры и Google держат favicon в своём кэше
     неделями и max-age не уважают; при следующей замене знака номер поднять. -->
<link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="16x16 32x32 48x48 64x64 128x128 256x256">
<link rel="icon" type="image/svg+xml" href="/assets/img/favicon.svg" sizes="any">
<link rel="icon" type="image/png" sizes="48x48" href="/assets/img/favicon-48.png">
<link rel="icon" type="image/png" sizes="96x96" href="/assets/img/favicon-96.png">
<link rel="icon" type="image/png" sizes="120x120" href="/assets/img/favicon-120.png">
<link rel="icon" type="image/png" sizes="192x192" href="/assets/img/favicon-192.png">
<link rel="apple-touch-icon" sizes="180x180" href="/assets/img/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="{theme_color}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="GEEKOVSKI">
<meta name="mobile-web-app-capable" content="yes">
{verify}
<link rel="alternate" type="application/rss+xml" title="GEEKOVSKI — лента" href="/rss.xml">
<link rel="alternate" type="application/rss+xml" title="GEEKOVSKI — дайджесты" href="/feed.xml">
<link rel="alternate" type="application/feed+json" title="GEEKOVSKI — JSON-лента" href="/feed.json">
<link rel="sitemap" type="application/xml" href="/sitemap.xml">
{head_extra}
<link rel="stylesheet" href="/assets/fonts.css">
<link rel="stylesheet" href="{theme_stylesheet}">
<link rel="stylesheet" href="/assets/brand.css">
<script>
document.documentElement.dataset.js = '';
try {{
  const mode = localStorage.getItem('gv-mode');
  if (mode) document.documentElement.dataset.mode = mode;
  if (localStorage.getItem('gv-sidebar') === 'compact') document.documentElement.dataset.sidebar = 'compact';
}} catch (e) {{}}
</script>
{metrika}
{ga}
{tmr}
{jsonld}
{digest_css}
</head>
<body class="t-{theme}">
{skip_link}
<header class="top">
  <div class="wrap top__in">
    <a class="brand" href="/" aria-label="GEEKOVSKI — блог">{brand_mark}<img class="brand__logo brand__logo--dark" src="/assets/img/geekovski-logo.svg" alt="" width="418" height="80"><img class="brand__logo brand__logo--light" src="/assets/img/geekovski-logo-light.svg" alt="" width="418" height="80"></a>
    <nav class="nav" id="site-nav" aria-label="Основное меню">{nav}</nav>
    <div class="top__actions">
      {side_links}<button class="theme-toggle" type="button" title="Сменить тему" aria-label="Сменить тему">◐</button>
      <button class="menu-toggle" type="button" aria-controls="site-nav" aria-expanded="false" aria-label="Открыть меню"><span></span><span></span><span></span></button>
    </div>
  </div>
{sidebar_toggle}</header>
{content}
<footer class="foot">
  <div class="wrap foot__in">
    <span class="foot__brand"><img src="/assets/img/favicon.svg" alt="" width="18" height="18">© {year} GEEKOVSKI</span>
    <span class="foot__note">Мнение в текстах отделено от факта. Источники — в конце каждой заметки.</span>
    <span class="foot__links"><a href="/avtory/">Авторы</a><a href="/about.html">О сайте</a><a href="/rss.xml">RSS</a><a class="foot__ext" href="{vk}" target="_blank" rel="noopener">ВКонтакте</a></span>
  </div>
</footer>
<script>
document.querySelector('.theme-toggle')?.addEventListener('click', () => {{
  const r = document.documentElement;
  const mode = r.dataset.mode || (r.dataset.theme === 'editorial' ? 'light' : 'dark');
  r.dataset.mode = mode === 'light' ? 'dark' : 'light';
  try {{ localStorage.setItem('gv-mode', r.dataset.mode); }} catch (e) {{}}
}});
const sidebarButton = document.querySelector('.sidebar-toggle');
if (sidebarButton) {{
  const root = document.documentElement;
  function updateSidebarLabel(compact) {{
    const label = compact ? 'Развернуть меню' : 'Свернуть меню';
    sidebarButton.setAttribute('aria-expanded', String(!compact));
    sidebarButton.setAttribute('aria-label', label);
    sidebarButton.title = label;
  }}
  updateSidebarLabel(root.dataset.sidebar === 'compact');
  sidebarButton.addEventListener('click', () => {{
    const compact = root.dataset.sidebar !== 'compact';
    if (compact) root.dataset.sidebar = 'compact';
    else delete root.dataset.sidebar;
    updateSidebarLabel(compact);
    try {{ localStorage.setItem('gv-sidebar', compact ? 'compact' : 'full'); }} catch (e) {{}}
  }});
}}
const menuButton = document.querySelector('.menu-toggle');
const siteNav = document.querySelector('#site-nav');
function closeMenu() {{
  menuButton?.setAttribute('aria-expanded', 'false');
  menuButton?.setAttribute('aria-label', 'Открыть меню');
  siteNav?.classList.remove('nav--open');
}}
menuButton?.addEventListener('click', () => {{
  const open = menuButton.getAttribute('aria-expanded') !== 'true';
  menuButton.setAttribute('aria-expanded', String(open));
  menuButton.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
  siteNav?.classList.toggle('nav--open', open);
}});
siteNav?.addEventListener('click', (event) => {{ if (event.target.closest('a')) closeMenu(); }});
const rubrics = document.querySelector('.nav__rubrics');
document.addEventListener('click', (event) => {{ if (rubrics?.open && !rubrics.contains(event.target)) rubrics.open = false; }});
document.addEventListener('keydown', (event) => {{
  if (event.key === 'Escape') {{
    if (menuButton?.getAttribute('aria-expanded') === 'true') menuButton.focus();
    closeMenu();
    if (rubrics) rubrics.open = false;
  }}
}});
if (document.documentElement.dataset.theme !== 'editorial') {{
  const route = location.pathname;
  const active = route === '/' ? '.nav__link--blog' : route.startsWith('/digests/') ? '.nav__link--digests' : '.nav__rubrics > summary';
  document.querySelector(active)?.classList.add('nav__link--active');
}}
</script>
<script>
(() => {{
  const btn = document.querySelector('[data-copy]');
  if (btn) btn.addEventListener('click', async () => {{
    const url = decodeURIComponent(btn.dataset.copy);
    try {{
      await navigator.clipboard.writeText(url);
      const old = btn.textContent; btn.textContent = 'Ссылка скопирована'; btn.classList.add('share__btn--done');
      setTimeout(() => {{ btn.textContent = old; btn.classList.remove('share__btn--done'); }}, 1800);
    }} catch (e) {{ window.prompt('Скопируйте ссылку', url); }}
  }});
}})();
</script>
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {{}}));
}}
</script>
</body>
</html>
"""


DEFAULT_OG = SITE["url"] + "/assets/img/og-default.png"
THEME_COLORS = {"editorial": "#F1F4F9"}
THEME_STYLESHEET = "/assets/theme.css"

# Счётчик Яндекс.Метрики. Отдельной строкой, а не внутри PAGE: код счётчика
# набит фигурными скобками, а PAGE собирается через str.format() — в шаблоне
# пришлось бы удваивать каждую. Подставляется как значение {metrika}.
METRIKA_COUNTER = """<!-- Yandex.Metrika counter -->
<script type="text/javascript">
    (function(m,e,t,r,i,k,a){
        m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
        m[i].l=1*new Date();
        for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
        k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
    })(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=114070859', 'ym');

    ym(114070859, 'init', {ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: location.href, accurateTrackBounce:true, trackLinks:true});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/114070859" style="position:absolute; left:-9999px;" alt="" /></div></noscript>
<!-- /Yandex.Metrika counter -->"""


# Счётчик Google Analytics 4 (gtag.js). Пустая строка = тега в разметке нет.
# Порядок подключения: завести поток в GA4 → прислать G-XXXXXXXXXX → прописать
# здесь → пересобрать сайт. Подставляется как значение {ga}.
GA_ID = ""
GA_TAG = "" if not GA_ID else """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=%s"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', '%s');
</script>
<!-- /Google tag -->""" % (GA_ID, GA_ID)


# Счётчик Top.Mail.Ru (Рейтинг Mail.Ru, VK). Как и счётчик Метрики — отдельной
# строкой, потому что код набит фигурными скобками и через str.format() не
# проходит. Подставляется как значение {tmr}. Пустая строка = счётчика нет.
TMR_COUNTER = """<!-- Top.Mail.Ru counter -->
<script type="text/javascript">
var _tmr = window._tmr || (window._tmr = []);
_tmr.push({id: "3816456", type: "pageView", start: (new Date()).getTime()});
(function (d, w, id) {
  if (d.getElementById(id)) return;
  var ts = d.createElement("script"); ts.type = "text/javascript"; ts.async = true; ts.id = id;
  ts.src = "https://top-fwz1.mail.ru/js/code.js";
  var f = function () {var s = d.getElementsByTagName("script")[0]; s.parentNode.insertBefore(ts, s);};
  if (w.opera == "[object Opera]") { d.addEventListener("DOMContentLoaded", f, false); } else { f(); }
})(document, window, "tmr-code");
</script>
<noscript><div><img src="https://top-fwz1.mail.ru/counter?id=3816456;js=na" style="position:absolute;left:-9999px;" alt="Top.Mail.Ru" /></div></noscript>
<!-- /Top.Mail.Ru counter -->"""


# ---------- SEO / GEO ----------
#
# canonical     — один документ = один адрес (иначе /index.html, /xbox/ и /xbox/index.html дают дубли);
# robots        — max-image-preview:large и max-snippet:-1: без них Яндекс и Google режут
#                 картинку и сниппет, а именно развёрнутый сниппет попадает в ответы AI-поиска;
# JSON-LD       — Organization/WebSite на всех страницах, BlogPosting + BreadcrumbList на
#                 материалах: оттуда поисковики и LLM берут дату, раздел, автора и источники;
# og:image мета — размеры читаются из файла, а не пишутся «1200×630» на веру: обложки на
#                 сайте бывают 16:9 и 4:3, и врущие width/height ломают превью ссылки.

ROBOTS_INDEX = "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
ROBOTS_NOINDEX = "noindex,follow"

# Подтверждение прав на домен в панелях вебмастеров. Значения не секретные,
# но менять их вручную в шапке нельзя: строка должна совпадать с той, что
# выдала панель, иначе подтверждение отваливается.
#   Яндек.Вебмастер → «Добавить сайт» → «Мета-тег» → сюда
#   Google Search Console → «HTML-тег» → GOOGLE_VERIFICATION
YANDEX_VERIFICATION = "acc866b9b963f469"
GOOGLE_VERIFICATION = ""
ZEN_VERIFICATION = "fcazccy74hGDyQJiYWhzVO7N3Kee8a2dhQQxuO7BiCeonKzNJ8udV93xNXeCPUpJ"

ORG_ID = SITE["url"] + "/#organization"
WEBSITE_ID = SITE["url"] + "/#website"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+03:00")


def _png_size(data):
    return struct.unpack(">II", data[16:24]) if len(data) >= 24 else None


def _jpeg_size(data):
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0…SOF15, кроме DHT (C4) и JPG (C8) — там нет размеров кадра
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seglen
    return None


def image_size(path: Path):
    try:
        with path.open("rb") as source:
            head = source.read(262144)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return _png_size(head)
    if head[:2] == b"\xff\xd8":
        return _jpeg_size(head)
    return None


def local_image(url):
    """Абсолютный URL обложки → файл в static/img (нужен для реальных размеров)."""
    prefix = SITE["url"] + "/assets/img/"
    if url and url.startswith(prefix):
        return ROOT / "static" / "img" / url[len(prefix):]
    return None


def webp_variant(path):
    """WebP-копия рядом с JPEG: ~вдвое меньше байт при том же размере кадра.

    GitHub Pages отдаёт картинки медленно и с большим TTFB, поэтому вес
    файла напрямую влияет на то, доедет ли кадр до читателя.
    """
    if not path or path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return None
    out = path.with_suffix(".webp")
    if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB") if im.mode not in ("RGB", "RGBA") else im
            im.save(out, "WEBP", quality=78, method=6)
        return out
    except Exception:
        return None


def image_tag(src, alt="", priority=False):
    if not src:
        return ""
    path = local_image(urllib.parse.urljoin(SITE["url"], src))
    size = image_size(path) if path else None
    dimensions = ' width="%d" height="%d"' % size if size else ""
    loading = 'fetchpriority="high"' if priority else 'loading="lazy" decoding="async"'
    img = f'<img src="{html.escape(src)}" alt="{html.escape(alt)}"{dimensions} {loading}>'
    webp = webp_variant(path)
    if webp and path is not None:
        rel = "/assets/img/" + webp.name
        return f'<picture><source srcset="{rel}" type="image/webp">{img}</picture>'
    return img


def og_image_meta(url, alt):
    url = url or DEFAULT_OG
    path = local_image(url)
    size = image_size(path) if path and path.exists() else None
    if size is None and url == DEFAULT_OG:
        size = (1200, 630)
    tags = ['<meta property="og:image" content="%s">' % html.escape(url, quote=True)]
    if size:
        tags.append('<meta property="og:image:width" content="%d">' % size[0])
        tags.append('<meta property="og:image:height" content="%d">' % size[1])
    tags.append('<meta property="og:image:alt" content="%s">' % html.escape(alt or SITE["title"], quote=True))
    return "\n".join(tags)


def ldjson(*objs):
    """Несколько сущностей одним графом JSON-LD (сайт, организация, статья, крошки)."""
    graph = [o for o in objs if o]
    payload = json.dumps({"@context": "https://schema.org", "@graph": graph},
                         ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return '<script type="application/ld+json">%s</script>' % payload


def ld_org():
    return {
        "@type": "Organization", "@id": ORG_ID, "name": SITE["title"],
        "url": SITE["url"] + "/", "description": SITE["tagline"],
        # каналы бренда: без sameAs поиск не связывает сайт и сообщество ВК
        "sameAs": [SITE["vk"]],
        "logo": {"@type": "ImageObject", "url": SITE["url"] + "/assets/img/icon-512.png",
                 "width": 512, "height": 512},
    }


def ld_website():
    return {
        "@type": "WebSite", "@id": WEBSITE_ID, "url": SITE["url"] + "/",
        "name": SITE["title"], "description": SITE["tagline"], "inLanguage": "ru-RU",
        "publisher": {"@id": ORG_ID},
    }


def ld_breadcrumb(crumbs):
    """Крошки задаются парами (название, путь от корня)."""
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE["url"] + path}
            for i, (name, path) in enumerate(crumbs)
        ],
    }


def breadcrumbs(crumbs, include_current=True):
    parents = crumbs[:-1] if include_current else crumbs
    links = "".join(f'<li><a href="{path}">{html.escape(name)}</a></li>' for name, path in parents)
    current = f'<li aria-current="page">{html.escape(crumbs[-1][0])}</li>' if include_current else ""
    return f'<nav class="breadcrumbs" aria-label="Путь к странице"><ol>{links}{current}</ol></nav>'


def ld_itemlist(posts, name):
    return {
        "@type": "ItemList", "name": name, "numberOfItems": len(posts),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "url": SITE["url"] + publication_path(p), "name": p["title"]}
            for i, p in enumerate(posts)
        ],
    }


SERVICE_SLUG = re.compile(r"(?:^|/)(?:\d{4}-\d{2}-\d{2}-)?(?:otchet|vecher|utro|kalendar)$")


def is_service(p) -> bool:
    """Материал-служебка: ежедневный отчёт, вечерний дайджест, календарь.

    Такие страницы тонкие и одинаковые по структуре — в sitemap им не место:
    на молодом домене они съедают краулинговый бюджет статей, а сами в выдачу
    не идут. Оставляем доступными (noindex,follow), чтобы не ломать ссылки.
    """
    if p.get("kind") == "digest":
        return True
    if (p.get("meta") or {}).get("noindex") in ("true", "1", "yes"):
        return True
    return bool(SERVICE_SLUG.search(p["slug"]))


def publication_path(p):
    directory = "/digests/" if p["kind"] == "digest" else "/"
    return f"{directory}{p['slug']}.html"


def ld_article(p, url, image_url=None, headline=None):
    """BlogPosting для материалов, Article для дайджестов.

    citation со ссылками на первоисточники — сигнал проверяемости: на такие страницы
    охотнее ссылаются ответы AI-поиска.
    """
    body_text = p["body"] if p["kind"] == "post" else " ".join(i["summary"] for i in p["items"])
    obj = {
        "@type": "Article" if p["kind"] == "digest" else "NewsArticle",
        "@id": url + "#article",
        "headline": headline or p["title"],
        "description": p["summary"] or plain(body_text, 160),
        "datePublished": iso(p["date"]),
        "dateModified": iso(p.get("updated") or p["date"]),
        "inLanguage": "ru-RU",
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "author": {"@id": ORG_ID},
        "publisher": {"@id": ORG_ID},
        "isAccessibleForFree": True,
        "articleSection": CAT_NAME.get(p["category"], p["category"]),
        "keywords": [CAT_NAME.get(p["category"], p["category"]), SITE["title"]],
        "wordCount": len(re.findall(r"\w+", body_text)),
        "isPartOf": {"@id": WEBSITE_ID},
    }
    img = image_url or (SITE["url"] + p["cover"] if p["cover"] else None)
    if img:
        entry = {"@type": "ImageObject", "url": img}
        path = local_image(img)
        size = image_size(path) if path and path.exists() else None
        if size:
            entry["width"], entry["height"] = size
        obj["image"] = [entry]
    cites = [s["url"] for s in p["sources"] if s.get("url")]
    if cites:
        obj["citation"] = cites
    if p.get("tldr"):
        obj["abstract"] = " ".join(p["tldr"])
    return obj


def verify_meta():
    tags = []
    if YANDEX_VERIFICATION:
        tags.append('<meta name="yandex-verification" content="%s">' % YANDEX_VERIFICATION)
    if GOOGLE_VERIFICATION:
        tags.append('<meta name="google-site-verification" content="%s">' % GOOGLE_VERIFICATION)
    if ZEN_VERIFICATION:
        tags.append('<meta name="zen-verification" content="%s" />' % ZEN_VERIFICATION)
    return "\n".join(tags)


def page(title, desc, content, theme, og_image=None, canonical=None, jsonld="",
         og_type="website", robots=ROBOTS_INDEX, article=None, og_alt=None,
         metrika=None, digest_css="", tmr=None, head_extra=""):
    canonical_tag = '<link rel="canonical" href="%s">' % html.escape(canonical, quote=True) if canonical else ""
    og_url = '<meta property="og:url" content="%s">' % html.escape(canonical, quote=True) if canonical else ""
    article_meta = ""
    if article:
        article_meta = "\n".join([
            '<meta property="article:published_time" content="%s">' % iso(article["date"]),
            '<meta property="article:modified_time" content="%s">' % iso(article.get("updated") or article["date"]),
            '<meta property="article:section" content="%s">' % html.escape(
                CAT_NAME.get(article["category"], article["category"]), quote=True),
            '<meta property="article:author" content="GEEKOVSKI">',
        ])
    editorial = theme == "editorial"
    return PAGE.format(
        theme_stylesheet=THEME_STYLESHEET,
        theme=theme, theme_color=THEME_COLORS.get(theme, "#0A0C0F"), title=html.escape(title), desc=html.escape(desc),
        nav=nav(theme, canonical), content=content.replace("<main", '<main id="main-content" tabindex="-1"', 1)
        if editorial else content, year=datetime.now().year, vk=SITE["vk"],
        skip_link='<a class="skip-link" href="#main-content">К содержанию</a>' if editorial else "",
        brand_mark=('<img class="brand__mark" src="/assets/img/geekovski-icon.svg" '
                    'alt="" width="32" height="32">') if editorial else "",
        sidebar_toggle=(
            '    <button class="sidebar-toggle" type="button" aria-controls="site-nav" aria-expanded="true" '
            'aria-label="Свернуть меню" title="Свернуть меню">'
            f'{sidebar_icon("collapse")}</button>\n'
            if editorial else ""),
        side_links=(f'<div class="top__links"><a href="/rss.xml">RSS</a>'
                    f'<a href="{SITE["vk"]}">ВКонтакте</a></div>') if editorial else "",
        og_image_meta=og_image_meta(og_image, og_alt or title),
        og_url=og_url, canonical=canonical_tag, robots=robots, og_type=og_type,
        article_meta=article_meta, jsonld=jsonld,
        verify=verify_meta(),
        metrika=METRIKA_COUNTER if metrika is None else metrika,
        ga=GA_TAG,
        tmr=TMR_COUNTER if tmr is None else tmr,
        digest_css=digest_css,
        head_extra=head_extra,
    )


def first_sentence(text, limit=170):
    """Ровно одно предложение для карточки ленты: режем по первой точке/!/?,
    но не даём предложению раздуться сверх limit символов."""
    text = (text or "").strip()
    if not text:
        return text
    m = re.search(r"[.!?…](\s|$)", text)
    sent = text[:m.end()].strip() if m else text
    if len(sent) > limit:
        cut = sent[:limit].rsplit(" ", 1)[0]
        sent = cut.rstrip(",;:—- ") + "…"
    return sent


def card(p, theme, big=False, summary=True, heading="h3", priority=False):
    cat = p["category"]
    cover = '<div class="card__cover">%s</div>' % image_tag(p["cover"], priority=priority) if p["cover"] else ""
    # чип рубрики — ссылка: даёт краулеру путь из каждой карточки в раздел
    return """<article class="card card--{cls} cat-{cat}">
{cover}  <div class="card__body">
    <div class="card__meta"><a class="chip cat-{cat}" href="/{cat}/">{catname}</a><time datetime="{isodt}">{date}</time></div>
    <{head_tag} class="card__title"><a href="/{slug}.html">{title}</a></{head_tag}>
{sum_block}{footer}  </div>
</article>""".format(
        cls="big" if big else "", cat=cat, catname=CAT_NAME.get(cat, cat), head_tag=heading,
        date=p["date"].strftime("%d.%m"), isodt=iso(p["date"]),
        slug=p["slug"], title=html.escape(p["title"]),
        sum_block=('    <p class="card__sum">%s</p>\n'
                   % html.escape(first_sentence(p["summary"] or plain(p["body"], 130),
                                                limit=125 if not big else 170))) if summary else "",
        cover=f'  {cover}\n' if cover else "",
        footer=('    <div class="card__foot"><a class="more" href="/%s.html">Читать →</a>%s</div>\n'
                % (p["slug"], '<span class="srcc">источников: %d</span>' % len(p["sources"])
                   if p["sources"] else "")) if theme != "editorial" else "",
    )


def hero(p):
    img = ('<div class="hero__cover"><img src="%s" alt="%s" loading="lazy"></div>'
           % (p["cover"], html.escape(p["title"], quote=True))) if p["cover"] else ""
    # .format() применяем ко ВСЕЙ склейке: иначе {slug} в первом литерале уходит в HTML буквально.
    # Чип внутри героя остаётся span: он лежит внутри <a class="hero__link">, а вложенная
    # ссылка — невалидный HTML, и браузер разорвёт разметку. Ссылки на рубрику дают карточки.
    return ("""<section class="hero">
  <a class="hero__link" href="/{slug}.html">
    """ + img + """
    <span class="chip chip--solid cat-{cat}">{catname}</span>
    <h1>{title}</h1>
    <p>{sum}</p>
    <span class="hero__cta">Читать разбор →</span>
  </a>
</section>""").format(
        slug=p["slug"], cat=p["category"], catname=CAT_NAME.get(p["category"], p["category"]),
        title=html.escape(p["title"]), sum=html.escape(p["summary"] or plain(p["body"], 220)),
    )


HOME_TITLE = "GEEKOVSKI — игры, технологии и кино: разборы и новости"
HOME_DESC = ("Разборы новостей игровой индустрии, техники, кино и AI: проверяемые факты, "
             "источники и даты. Xbox, PlayStation, Nintendo Switch, PC, VR и гаджеты.")
HOME_POST_LIMIT = 12


def rubric_links(current=None):
    canonical = f"{SITE['url']}/{current}/" if current else None
    links = "".join(nav_link(f"/{slug}/", name, canonical) for slug, name in CATS)
    return f'<nav class="topic-nav" aria-label="Рубрики блога">{links}</nav>'


def editorial_front(posts):
    intro = ('''<header class="home-intro">
  <h1>Игры, технологии и кино</h1>
  <p>Новости и разборы с источниками.<br> Без маркетингового сиропа.</p>
</header>''')
    top_cards = "\n".join(card(p, "editorial", big=i == 0, summary=i == 0, priority=i == 0)
                           for i, p in enumerate(posts[:3]))
    fresh = f'<div class="home-stories">{top_cards}</div>' if top_cards else '<p class="home-empty">Публикаций пока нет.</p>'
    first = (f'<section class="home-front" aria-labelledby="fresh-title">'
             f'<div class="home-edition"><h2 id="fresh-title">Свежие материалы</h2>'
             f'<a href="/archive/">Архив публикаций <span aria-hidden="true">↗</span></a></div>{fresh}</section>')

    more = ""
    if len(posts) > 3:
        cards = "\n".join(card(p, "editorial", summary=False) for p in posts[3:HOME_POST_LIMIT])
        more = (f'<section class="home-more" aria-labelledby="more-title"><div class="section-head">'
                f'<h2 id="more-title">Ещё из блога</h2></div><div class="editorial-grid">{cards}</div>'
                f'<a class="archive-door" href="/archive/">Весь архив <span aria-hidden="true">↗</span></a></section>')
    return f'<main class="wrap home">{intro}{first}{more}</main>'


def render_index(posts, theme):
    if theme == "editorial":
        return page(HOME_TITLE, HOME_DESC, editorial_front(posts), theme,
                    canonical=SITE["url"] + "/", og_alt="GEEKOVSKI — игры, технологии и кино",
                    jsonld=ldjson(ld_org(), ld_website(),
                                  ld_itemlist(posts[:HOME_POST_LIMIT], "Свежие материалы GEEKOVSKI") if posts else None))
    if not posts:
        return page(HOME_TITLE, HOME_DESC, '<main class="wrap"><p>Пусто.</p></main>', theme,
                    canonical=SITE["url"] + "/", jsonld=ldjson(ld_org(), ld_website()))
    head = hero(posts[0])
    cards = "\n".join(card(p, theme) for p in posts[1:])
    content = '<main class="wrap"><div class="hero-wrap">%s</div><div class="grid grid--mag">%s</div></main>' % (head, cards)
    return page(HOME_TITLE, HOME_DESC, content, theme,
                canonical=SITE["url"] + "/",
                og_alt="GEEKOVSKI — игры, технологии и кино",
                jsonld=ldjson(ld_org(), ld_website(),
                              ld_itemlist(posts[:12], "Свежие материалы GEEKOVSKI")))


ARCHIVE_CRUMBS = [("Блог", "/"), ("Архив", "/archive/")]


def archive_months(posts):
    months = collections.defaultdict(list)
    for post in posts:
        months[post["date"].strftime("%Y-%m")].append(post)
    return dict(sorted(months.items(), reverse=True))


def archive_month_path(key):
    return f"/archive/{key}/"


def archive_month_name(key):
    year, month = key.split("-")
    return f"{MONTHS_NOM[int(month) - 1]} {year}"


def archive_page(theme, heading, description, body, crumbs, items=None):
    url = SITE["url"] + crumbs[-1][1]
    content = (f'<main class="wrap archive-page">{breadcrumbs(crumbs)}'
               f'<header class="collection-head"><h1>{heading}</h1><p>{description}</p></header>'
               f'{body}</main>')
    return page(title_tag(heading), description, content, theme, canonical=url,
                jsonld=ldjson(ld_org(), ld_website(), ld_breadcrumb(crumbs),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": heading, "description": description, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}},
                              ld_itemlist(items, heading) if items else None))


def render_archive(months, theme):
    links = "".join(f'<li><a href="{archive_month_path(key)}">{archive_month_name(key)} '
                    f'<span>{len(items)} {plural(len(items), "материал", "материала", "материалов")}</span>'
                    f'</a></li>' for key, items in months.items())
    body = f'<ul class="archive-list archive-list--months">{links}</ul>' if links else '<p>Публикаций пока нет.</p>'
    return archive_page(theme, "Архив публикаций", "Новости и разборы GEEKOVSKI по месяцам.", body, ARCHIVE_CRUMBS)


def render_archive_month(key, items, theme):
    name = archive_month_name(key)
    description = f"{name}. Новости и разборы об играх, технологиях и кино в архиве GEEKOVSKI."
    rows = "".join(f'<li><time datetime="{iso(p["date"])}">{p["date"]:%d.%m}</time>'
                   f'<a href="{publication_path(p)}">{html.escape(p["title"])}</a>'
                   f'<span>{CAT_NAME[p["category"]]}</span></li>' for p in items)
    body = f'<ul class="archive-list">{rows}</ul>'
    return archive_page(theme, name, description, body,
                        ARCHIVE_CRUMBS + [(name, archive_month_path(key))], items)


# ---------- перелинковка: тайтл ↔ статьи ----------

def _aliases(t):
    """Как тайтл может упоминаться в тексте: заголовок, короткое имя и slug-варианты."""
    names = [t["title"]]
    raw = t.get("aliases") or ""
    if raw:
        names += [x.strip() for x in raw.split("|") if x.strip()]
    return [n for n in names if len(n) >= 3]


def configure_title_mentions():
    """Сопоставляем только однозначные названия, от длинных к коротким."""
    global TITLE_MENTION_PATTERN
    candidates = collections.defaultdict(set)
    for slug, title in TITLES.items():
        for name in _aliases(title):
            candidates[name.lower()].add(slug)
    TITLE_ALIASES.clear()
    TITLE_ALIASES.update(
        (name, next(iter(slugs))) for name, slugs in candidates.items() if len(slugs) == 1
    )
    names = sorted(TITLE_ALIASES, key=len, reverse=True)
    TITLE_MENTION_PATTERN = re.compile(
        r"(?<![\w\[/])(" + "|".join(map(re.escape, names)) + r")(?![\w\]])",
        re.IGNORECASE,
    ) if names else None


def link_articles_to_titles(html_text):
    """Первое упоминание тайтла в тексте статьи → ссылка на его страницу.
    Работает по чистому тексту ДО markdown, поэтому длинные имена
    обрабатываются первыми и ссылки не вкладываются друг в друга."""
    if TITLE_MENTION_PATTERN is None:
        return html_text
    # Уже готовые markdown-картинки и ссылки прячем в плейсхолдеры: иначе алиас
    # тайтла в подписи картинки рвал синтаксис («!<a …>-switch-2-hp.jpg)»),
    # и на странице появлялась битая картинка вместо кадра.
    stash = []

    def _stash(m):
        stash.append(m.group(0))
        return "\x00%d\x00" % (len(stash) - 1)

    html_text = re.sub(r"!\[[^\]]*\]\([^)]*\)", _stash, html_text)
    html_text = re.sub(r"\[[^\]]*\]\([^)]*\)", _stash, html_text)
    # Один проход вместо цикла «найти и вставить»: во втором случае вставленный
    # markdown-линк успевал попасть под следующий, более короткий алиас —
    # «Stellar Blade» ловился алиасом «Blade» другого тайтла, и в href получалось
    # /titles/stellar-[blade](/titles/marvels-blade.html. re.sub вставленный
    # текст заново не сканирует, поэтому вложенных ссылок не бывает.
    done = {
        slug for link in stash if not link.startswith("!")
        for slug in TITLE_LINK_PATTERN.findall(link)
    }

    def _rep(m):
        slug = TITLE_ALIASES.get(m.group(1).lower())
        if slug is None or slug in done:
            return m.group(1)
        done.add(slug)
        return "[%s](/titles/%s.html)" % (m.group(1), slug)

    linked = TITLE_MENTION_PATTERN.sub(_rep, html_text)
    if stash:
        linked = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], linked)
    return linked


def index_title_mentions(posts):
    """Собираем обратные ссылки из тех же упоминаний и явных редакционных ссылок."""
    TITLE_ARTICLES.clear()
    if TITLE_MENTION_PATTERN is None:
        return
    for post in posts:
        parts = [post["title"], post["summary"], post["body"] or ""]
        if post["kind"] == "digest":
            parts.extend(item["title"] + " " + item["summary"] for item in post["items"])
        text = "\n".join(parts)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        explicit = TITLE_LINK_PATTERN.findall(text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        slugs = set(explicit) & TITLES.keys()
        slugs.update(
            TITLE_ALIASES.get(m.group(1).lower()) for m in TITLE_MENTION_PATTERN.finditer(text)
        )
        for slug in slugs - {None}:
            if len(TITLE_ARTICLES[slug]) < 12:
                TITLE_ARTICLES[slug].append(post)


def back_link(label=None, href=None):
    """Кнопка «назад». Сначала история браузера, иначе — ссылка по контексту."""
    label = label or "Назад"
    fallback = href or "/"
    return ('<div class="backrow"><a class="backlink" href="%s" '
            'onclick="if(document.referrer){history.back();return false}">'
            '<span class="backlink__arrow" aria-hidden="true">←</span> %s</a></div>'
            % (fallback, label))



def offline_page(theme):
    """Заглушка для установленного приложения, когда сети нет."""
    content = ('<main class="wrap"><section class="lead"><h1>Нет соединения</h1>'
               '<p>Страница не загрузилась — похоже, пропал интернет. Уже открытые материалы '
               'доступны, а свежие появятся, как только связь вернётся.</p></section></main>')
    return page("Нет соединения — %s" % SITE["title"], "Страница недоступна без интернета.",
                content, theme, robots="noindex,nofollow")


def share_block(url, title, image=None):
    """Кнопки «поделиться». Ссылки — обычные share-URL соцсетей, без сторонних скриптов."""
    u = urllib.parse.quote(url, safe="")
    tx = urllib.parse.quote(title, safe="")
    img = urllib.parse.quote(image or DEFAULT_OG, safe="")
    return ("""<section class="share" data-share-root>
  <span class="share__label">Поделиться</span>
  <a class="share__btn" href="https://t.me/share/url?url={u}&text={t}" target="_blank" rel="noopener nofollow">Telegram</a>
  <a class="share__btn" href="https://vk.com/share.php?url={u}&title={t}" target="_blank" rel="noopener nofollow">ВКонтакте</a>
  <a class="share__btn" href="https://x.com/intent/tweet?url={u}&text={t}" target="_blank" rel="noopener nofollow">X</a>
  <a class="share__btn" href="https://ru.pinterest.com/pin/create/button/?url={u}&media={i}&description={t}" target="_blank" rel="noopener nofollow">Pinterest</a>
  <button class="share__btn share__btn--copy" type="button" data-copy="{u}">Пошерить</button>
</section>""").format(u=u, t=tx, i=img)


def article_contents(body):
    headings = list(re.finditer(r"<h2>(.*?)</h2>", body, re.S))
    if len(headings) < 3:
        return body, ""
    used = set()
    links = []
    parts, end = [], 0
    for heading in headings:
        label = re.sub(r"<[^>]+>", "", heading[1])
        base = "section-" + title_slug(html.unescape(label))
        anchor, suffix = base, 1
        while anchor in used:
            suffix += 1
            anchor = f"{base}-{suffix}"
        used.add(anchor)
        parts.extend([body[end:heading.start()], f'<h2 id="{anchor}">{heading[1]}</h2>'])
        end = heading.end()
        links.append(f'<li><a href="#{anchor}">{label}</a></li>')
    items = "".join(links)
    toc = (f'<details class="article-toc" open><summary>Содержание</summary>'
           f'<nav aria-label="Содержание статьи"><ul>{items}</ul></nav></details>'
           '<script>if(matchMedia("(max-width: 1169px)").matches)'
           'document.currentScript.previousElementSibling.open=false;</script>')
    return "".join(parts) + body[end:], toc


def contextual_links(p, posts, limit=3):
    """Контекстные ссылки в теле статьи — не карточки, а строки текста.

    Карточки «По теме» стоят внизу и в тексте не считаются; поисковику же важны
    ссылки внутри абзацев, с осмысленным анкором. Собираем три: две из своей
    рубрики и одну из соседней с общим словом в заголовке.
    """
    def words(t):
        return {w.lower() for w in re.findall(r"[А-Яа-яA-Za-z]{4,}", t)}

    mine = [x for x in posts if x["slug"] != p["slug"]]
    own_words = words(p["title"])
    same = [x for x in mine if x["category"] == p["category"]]
    other = [x for x in mine if x["category"] != p["category"]]
    picked = []
    for x in same:
        if len(picked) < 2:
            picked.append(x)
    for x in sorted(other, key=lambda y: -len(own_words & words(y["title"]))):
        if len(own_words & words(x["title"])) >= 1:
            picked.append(x)
            break
    if len(picked) < limit:
        for x in same[2:]:
            picked.append(x)
            if len(picked) >= limit:
                break
    return picked[:limit]


def render_post(p, posts, theme):
    more = contextual_links(p, posts)
    _more_slugs = {x["slug"] for x in more}
    related = [x for x in posts if x["category"] == p["category"]
               and x["slug"] != p["slug"] and x["slug"] not in _more_slugs][:3]
    p = dict(p, body=link_articles_to_titles(p["body"]))
    srcs = ""
    if p["sources"]:
        srcs = '<section class="sources"><h2>Источники</h2><ol>%s</ol></section>' % "".join(
            '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>' % (html.escape(s["url"]), html.escape(s["name"]))
            if s["url"] else "<li>%s</li>" % html.escape(s["name"]) for s in p["sources"])
    body = md(p["body"])
    editorial = theme == "editorial"
    toc = ""
    if editorial:
        body, toc = article_contents(body)
    # «Коротко»: список фактов из frontmatter tldr — то, что можно процитировать
    # в ответе, не пересказывая статью.
    tldr = ""
    if p.get("tldr"):
        tldr = ('<aside class="tldr"><h2 class="tldr__title">Коротко</h2><ul>%s</ul></aside>'
                % "".join("<li>%s</li>" % md_inline(x) for x in p["tldr"]))
    cover = ""
    if p["cover"]:
        cover = ('<figure class="post__cover">%s</figure>' %
                 image_tag(p["cover"], p["meta"].get("cover_alt") or p["title"], priority=True))
    # CC BY / CC BY-SA требуют указания автора и лицензии: держим их мелкой строкой в конце,
    # а не подписью под картинкой. CC0 и public domain — без упоминания.
    credit_line = ""
    if p.get("credit") and "CC BY" in p["credit"]:
        credit_line = ('<p class="imgcredit">Изображения: %s</p>'
                       % html.escape(p["credit"].replace("Обложка: ", "")))
    rel = ""
    if related:
        grid = 'editorial-grid' if editorial else 'grid grid--list'
        rel = f'<section class="related"><h2>По теме</h2><div class="{grid}">%s</div></section>' % "\n".join(
            card(x, theme) for x in related)
    # подпись автора: страница редакции должна быть достижима из каждого материала,
    # иначе она висит сиротой и в поиске не набирает вес
    byline = ""
    _author = AUTHOR_BY_CAT.get(p["category"])
    if _author:
        # подпись: аватар, слово «Автор» и полное имя капителью Chava — так же,
        # как подписаны метки сайта, чтобы подпись не выглядела чужой врезкой.
        # Пробел между меткой и именем — для читалок и режимов без CSS: там спаны
        # схлопываются в строку «АвторМарк Стрельцов», если пробела нет; во flex-
        # колонке этот пробельный текстовый узел не рендерится.
        byline = ('<p class="byline"><img class="byline__pic" src="%s" alt="" width="40" height="40" loading="lazy">'
                  '<span class="byline__text"><span class="byline__label">Автор</span> '
                  '<a class="byline__name" href="/avtory/%s.html">%s</a></span></p>'
                  % (html.escape(_author["avatar"]), _author["slug"],
                     html.escape(_author["full_name"] or _author["name"])))
    path = publication_path(p)
    catname = CAT_NAME[p["category"]]
    crumbs = [("Блог", "/"), ("Категории", CATEGORIES_PATH), (catname, f'/{p["category"]}/'), (p["title"], path)]
    published = p["date"]
    date = f"{ru_date(published)} {published:%Y, %H:%M}" if editorial else published.strftime("%d.%m.%Y, %H:%M")
    time = f'<time datetime="{iso(published)}">{date}</time>'
    meta = ""
    if editorial:
        byline = f'<div class="post__creditline">{byline}{time}</div>'
    else:
        meta = (f'<div class="post__meta"><a class="chip chip--solid cat-{p["category"]}" '
                f'href="/{p["category"]}/">{catname}</a>{time}</div>')
    share = share_block(SITE["url"] + path, p["title"],
                        SITE["url"] + (p["pin"] or p["cover"]) if (p["pin"] or p["cover"]) else None)
    more_block = ""
    if more:
        # карточки, а не строки: у каждой обложка и рубрика — так блок читается
        # как продолжение ленты, а не как список сносок
        more_block = ('<nav class="post__more" aria-label="Другие материалы по теме">'
                      '<h2>Читайте также</h2><div class="morecards">%s</div></nav>'
                      % "".join(card(x, theme, summary=False, priority=True) for x in more))
    reading = f'<div class="post__body">{body}{more_block}</div>{credit_line}{srcs}{share}'
    if editorial:
        layout = "reading-layout--toc" if toc else ""
        reading = f'<div class="reading-layout {layout}">{cover}{toc}<div class="reading-text">{tldr}{reading}</div></div>'
    else:
        reading = f'{tldr}{cover}{reading}'
    content = """<main class="wrap post-page">
{back}
<article class="post cat-{cat}">
  <header class="post__head">
{meta}    <h1>{title}</h1>
    {lead}
    {byline}
  </header>
  {reading}
</article>
{rel}
</main>""".format(
        cat=p["category"], meta=f"    {meta}\n" if meta else "",
        title=html.escape(p["title"]),
        lead=f'<p class="post__lead">{html.escape(p["summary"])}</p>' if p["summary"] else "",
        reading=reading, rel=rel, byline=byline,
        back=breadcrumbs(crumbs[:-1], include_current=False) if editorial else back_link("Назад", f'/{p["category"]}/'),
    )
    og = SITE["url"] + p["cover"] if p["cover"] else None
    url = SITE["url"] + path
    return page(title_tag(p["title"]),
                p["summary"] or plain(p["body"], 160),
                content, theme, og_image=og, canonical=url, og_type="article",
                article=p, og_alt=p["title"],
                robots=ROBOTS_NOINDEX if is_service(p) else ROBOTS_INDEX,
                jsonld=ldjson(ld_org(), ld_website(), ld_article(p, url),
                              ld_breadcrumb(crumbs)))


def title_tag(text, brand=SITE["title"], limit=68):
    """Заголовок для <title>: бренд добавляем только если влезаем в сниппет.

    Длинный H1 (а он у нас любит быть длинным) с « — GEEKOVSKI» превращается в 90+
    символов, и поиск обрезает самое важное — начало. Бренд в этом случае лишний:
    домен и так подписан в выдаче.
    """
    if len(text) + 3 + len(brand) <= limit:
        return "%s — %s" % (text, brand)
    return text


def render_categories(theme):
    description = "Все категории блога GEEKOVSKI: игры, гаджеты, кино, сериалы и искусственный интеллект."
    crumbs = [("Блог", "/"), ("Категории", CATEGORIES_PATH)]
    cards = "".join(f'<li><h2><a href="/{slug}/">{name} <span aria-hidden="true">↗</span></a></h2>'
                    f'<p>{CAT_DESCRIPTION[slug]}</p></li>' for slug, name in CATS)
    content = (f'<main class="wrap category-page">{breadcrumbs(crumbs)}'
               f'<header class="collection-head"><h1>Категории</h1></header>'
               f'<ul class="category-index">{cards}</ul></main>')
    url = SITE["url"] + CATEGORIES_PATH
    return page(title_tag("Категории"), description, content, theme, canonical=url,
                jsonld=ldjson(ld_org(), ld_website(), ld_breadcrumb(crumbs),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": "Категории", "description": description, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}}))


def render_cat(slug, name, items, theme):
    editorial = theme == "editorial"
    cards = "\n".join(card(p, theme, heading="h2") for p in items)
    count = "%d %s" % (len(items), plural(len(items), "материал", "материала", "материалов"))
    desc = CAT_DESCRIPTION[slug]
    if items:
        grid = "editorial-grid" if editorial else ("grid grid--cards" if theme == "dashboard" else "grid grid--list")
        body = f'<div class="{grid}">{cards}</div>'
    else:
        # пустая рубрика не должна выглядеть сломанной: говорим прямо и уводим в дайджесты
        body = ('<p class="lead__empty">Здесь пока пусто — рубрика только открылась. '
                'Свежие новости по всем направлениям выходят в <a href="/digests/">дайджестах</a>, '
                'а разборы появляются <a href="/">в блоге</a>.</p>')
    path = f"/{slug}/"
    crumbs = [("Блог", "/"), ("Категории", CATEGORIES_PATH), (name, path)]
    if editorial:
        content = (f'<main class="wrap category-page">{breadcrumbs(crumbs)}'
                   f'<header class="collection-head"><h1>{html.escape(name)}</h1><p>{desc}</p></header>'
                   f'{rubric_links(slug)}{body}</main>')
    else:
        content = ('<main class="wrap">%s<section class="lead"><h1>%s</h1><p>%s</p></section>%s</main>'
                   % (back_link("На главную", "/"), html.escape(name),
                      count if items else "рубрика открыта", body))
    url = SITE["url"] + path
    return page("%s — новости и разборы | %s" % (name, SITE["title"]), desc, content, theme,
                canonical=url, og_alt="%s — GEEKOVSKI" % name,
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": name, "description": desc, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}},
                              ld_itemlist(items, name) if items else None,
                              ld_breadcrumb(crumbs)))


def load_authors(content_dir=None):
    """Паспорта авторов из content/authors/*.md.

    Тот же формат, что у простых страниц (frontmatter + markdown), поэтому
    редактор правит автора обычной заметкой, а не кодом сборки.
    """
    base = (Path(content_dir) if content_dir else ROOT / "content") / "authors"
    if not base.exists():
        return []
    out = []
    for path in sorted(base.glob("*.md")):
        meta, body = parse_page(path)
        if not meta.get("name"):
            continue
        try:
            order = int(meta.get("order") or 99)
        except ValueError:
            order = 99
        out.append({
            "slug": meta.get("slug") or path.stem,
            "name": meta["name"],
            "full_name": meta.get("full_name", ""),
            "role": meta.get("role", ""),
            "avatar": meta.get("avatar", ""),
            "scene": meta.get("scene", ""),
            "summary": meta.get("summary", ""),
            "order": order,
            "categories": (meta.get("categories") or "").split(),
            "body": body,
        })
    out.sort(key=lambda a: (a["order"], a["name"]))
    return out


def _author_names(a):
    """Имя и фамилия + короткое имя, которым автор подписан в текстах.

    Паспорт автора держит оба: `full_name` — как человек подписан на странице
    редакции («Всеволод Гринёв»), `name` — как подпись под статьёй («Сева»).
    В карточке нужно первое, а второе — чтобы читатель связал одно с другим.
    """
    full = (a.get("full_name") or a.get("name") or "").strip()
    nick = (a.get("name") or "").strip()
    if nick == full:
        nick = ""
    role = (a.get("role") or "").strip()
    meta = " · ".join(x for x in (nick, role) if x)
    return full, nick, meta


def _authcard(a):
    """Карточка автора: круглый портрет, имя и фамилия капителью Chava,
    ниже — короткое имя с ролью и одна фраза о том, чем человек занят."""
    full, _nick, meta = _author_names(a)
    return ('<a class="authcard" href="/avtory/%s.html">'
            '<span class="authcard__head">'
            '<img class="authcard__pic" src="%s" alt="%s" width="132" height="132" loading="lazy">'
            '<span class="authcard__id">'
            '<span class="authcard__name">%s</span>'
            '<span class="authcard__role">%s</span>'
            '</span></span>'
            '<span class="authcard__sum">%s</span>'
            '<span class="authcard__go">Профиль и материалы <span aria-hidden="true">→</span></span>'
            '</a>') % (
        a["slug"], html.escape(a["avatar"]), html.escape(full, quote=True),
        html.escape(full), html.escape(meta), html.escape(a["summary"]))


def own_studio_strip():
    """Кадр студии и кот-символ под составом редакции.

    Фотографий меньше, чем текста, поэтому студия — единственный блок ниже карточек:
    она объясняет, почему у канала вообще есть «место», а не только три подписи.
    """
    wide, cat = ROOT / "static" / "img" / "studio.jpg", ROOT / "static" / "img" / "mascot-cat-shelf.jpg"
    if not (wide.exists() and cat.exists()):
        return ""
    return ('<section class="studio">'
            '<figure class="studio__big"><img src="/assets/img/studio.jpg" alt="Студия редакции: '
            'полки с консолями, коробки и посылки" loading="lazy"></figure>'
            '<div class="studio__side">'
            '<p class="studio__label">Студия</p>'
            '<p class="studio__text">Общая комната, куда мы приходим работать: полки со старыми '
            'консолями, коробки от посылок с техникой, тёплый свет. На средней полке живёт кот — '
            'белый, пушистый, и он у нас за главного.</p>'
            '<figure class="studio__cat"><img src="/assets/img/mascot-cat-shelf.jpg" alt="Белый кот '
            'студии сидит на полке рядом с консолями" loading="lazy"></figure>'
            '</div></section>')


def render_authors_index(authors, theme):
    """Страница /avtory/ — кто ведёт редакцию и что каждый закрывает."""
    cards = "".join(_authcard(a) for a in authors)
    n = len(authors)
    lead = ("%d %s, которые ведут GEEKOVSKI: у каждого своя тема и свой голос. "
            "Материалы в ленте подписаны — по подписи видно, кто отвечает за текст."
            % (n, plural(n, "человек", "человека", "человек")))
    content = ('<main class="wrap">%s<section class="lead"><h1>Редакция</h1><p>%s</p></section>'
               '<div class="authors">%s</div>%s%s</main>'
               % (back_link("На главную", "/"), lead, cards,
                  ('<p class="authors__feeds">Ленты авторов: %s</p>'
                   % " · ".join('<a href="/avtory/%s.xml">%s</a>'
                                % (a["slug"], html.escape(a["name"])) for a in authors))
                  if authors else "",
                  own_studio_strip()))
    url = SITE["url"] + "/avtory/"
    desc = "Редакция GEEKOVSKI: кто пишет про железо, игры и кино — и за что отвечает."
    return page("Редакция — кто пишет GEEKOVSKI", desc, content, theme, canonical=url,
                og_alt="Редакция GEEKOVSKI",
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": "Редакция GEEKOVSKI", "description": desc,
                               "inLanguage": "ru-RU", "isPartOf": {"@id": WEBSITE_ID}},
                              ld_breadcrumb([("Главная", "/"), ("Редакция", "/avtory/")])))


def author_posts(a, posts):
    """Материалы автора: рубрики его паспорта, свежие вперёд.

    Одна функция и для страницы автора, и для его ленты — иначе страница и фид
    незаметно разъезжаются (в фиде остаётся рубрика, которую снял редактор).
    """
    cats = [c for c in a["categories"] if c in CAT_NAME]
    return [p for p in posts if p["category"] in cats]


def author_feed(a, posts):
    """Лента автора: /avtory/<slug>.xml — та же RSS 2.0, что у сайта.

    Нужна, чтобы читатель подписывался на одного человека, а не на весь канал:
    у Севы железо, у Марка игры, у Ани кино, и мешать их в одной читалке незачем.
    """
    full, _nick, _meta = _author_names(a)
    return rss(posts, title="%s — %s" % (SITE["title"], full),
               self_name="avtory/%s.xml" % a["slug"],
               desc="%s, %s. Материалы с сайта geekovski.ru." % (full, a["role"]))


def author_page(a, posts, theme):
    """Страница автора: круглый портрет, имя и фамилия капителью Chava,
    короткое описание, его материалы по рубрикам и ссылка на его ленту."""
    cats = [c for c in a["categories"] if c in CAT_NAME]
    mine = author_posts(a, posts)
    # на странице автора — весь его архив, а не первые двенадцать: за этим
    # страница и нужна (как рубрика, только по человеку). В ленте — FEED_LIMIT.
    items = mine
    total = len(mine)
    full, _nick, meta = _author_names(a)
    name = html.escape(full)
    feed = "/avtory/%s.xml" % a["slug"]
    url = "%s/avtory/%s.html" % (SITE["url"], a["slug"])
    if items:
        body = ('<div class="grid grid--list">%s</div>'
                % "\n".join(card(p, theme) for p in items))
        head2 = ("Материалы: %s" % ", ".join(CAT_NAME[c] for c in cats))
    else:
        body = ('<p class="lead__empty">Материалов пока нет — свежие новости по этим темам '
                'выходят в <a href="/digests/">дайджестах</a>.</p>')
        head2 = "Материалы"
    count_line = ('%d %s · <a class="feed__link" href="%s">Лента автора (RSS)</a>'
                  % (total, plural(total, "материал", "материала", "материалов"), feed)
                  ) if total else ('<a class="feed__link" href="%s">Лента автора (RSS)</a>' % feed)
    content = ('<main class="wrap">%s'
               '<section class="author">'
               '<img class="author__pic" src="%s" alt="%s" width="420" height="420">'
               '<div class="author__about">'
               '<h1 class="author__name">%s</h1>'
               '<p class="author__role">%s</p>'
               '<p class="author__lead">%s</p>'
               '<div class="author__body">%s</div>'
               '</div></section>'
               '%s'
               '<section class="lead"><h2>%s</h2><p>%s</p></section>'
               '%s</main>') % (
        back_link("Все авторы", "/avtory/"),
        html.escape(a["avatar"]), html.escape(full, quote=True),
        name, html.escape(meta), html.escape(a["summary"]), md(a["body"]),
        ('<figure class="author__scene"><img src="%s" alt="%s"></figure>'
         % (html.escape(a["scene"]), html.escape(full, quote=True))) if a.get("scene") else "",
        html.escape(head2),
        count_line,
        body)
    desc = a["summary"] or plain(a["body"], 160)
    return page(title_tag("%s — %s" % (full, a["role"].replace(" · ", ", "))),
                desc, content, theme, canonical=url, og_image=SITE["url"] + a["avatar"] if a["avatar"] else None,
                og_alt=full,
                head_extra=('<link rel="alternate" type="application/rss+xml" title="%s — лента" href="%s">'
                            % (html.escape(full, quote=True), feed)),
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "ProfilePage", "@id": url + "#page", "url": url,
                               "name": "%s — %s" % (full, a["role"]), "description": desc,
                               "inLanguage": "ru-RU", "isPartOf": {"@id": WEBSITE_ID},
                               "mainEntity": {"@type": "Person", "@id": url + "#person",
                                              "name": full,
                                              "alternateName": a["name"],
                                              "jobTitle": a["role"],
                                              "description": a["summary"],
                                              "image": SITE["url"] + a["avatar"] if a["avatar"] else None,
                                              "url": url,
                                              "worksFor": {"@id": ORG_ID}}},
                              ld_breadcrumb([("Главная", "/"), ("Редакция", "/avtory/"),
                                             (full, "/avtory/%s.html" % a["slug"])])))


RSS_NS = ('xmlns:atom="http://www.w3.org/2005/Atom" '
          'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
          'xmlns:dc="http://purl.org/dc/elements/1.1/" '
          'xmlns:media="http://search.yahoo.com/mrss/"')

FEED_LIMIT = 40          # сколько материалов в ленте; в JSON-фиде — все
# Полный текст в <content:encoded>. True — подписчик читает статью в читалке,
# False — в ленте остаётся только summary со ссылкой (и трафик идёт на сайт).
FEED_FULL_TEXT = True
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".webp": "image/webp", ".gif": "image/gif"}
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def rfc822(dt):
    """Дата в формате RFC 822 по-английски.

    strftime("%a, %d %b %Y") печатает день и месяц на языке локали машины:
    на русской локали в ленту уехало бы «Вт, 17 ноя 2026», и читалки
    показали бы записи без даты.
    """
    return "%s, %02d %s %04d %02d:%02d:%02d +0300" % (
        _DAYS[dt.weekday()], dt.day, _MONTHS[dt.month - 1], dt.year,
        dt.hour, dt.minute, dt.second)


def _feed_abs(fragment):
    """«/assets/…» → абсолютный URL: читалка грузит картинку со своего домена,
    и относительный путь там уходит в 404."""
    return re.sub(r'\b(src|href)="/(?!/)', r'\1="%s/' % SITE["url"], fragment)


def _feed_cover(p):
    """<enclosure> и <media:content> обложки.

    Без них лента выглядит списком строк: превью в Telegram-ботах и агрегаторах
    (в том числе Дзен-РСС) строится из enclosure, а не из ссылки на статью.
    """
    if not p["cover"]:
        return ""
    path = ROOT / "static" / p["cover"].replace("/assets/", "", 1)
    length = path.stat().st_size if path.exists() else 0
    mime = _MIME.get(path.suffix.lower(), "image/jpeg")
    url = html.escape(SITE["url"] + p["cover"], quote=True)
    return ('<enclosure url="%s" length="%d" type="%s"/>'
            '<media:content url="%s" medium="image" type="%s"/>' % (url, length, mime, url, mime))


def _feed_html(p):
    """Полный текст материала для <content:encoded>.

    Подписчик читает статью в читалке и не возвращается на сайт ради одного
    абзаца. Источники остаются в конце — то же правило, что на странице.
    """
    parts = []
    if p["cover"]:
        parts.append('<figure><img src="%s" alt="%s"></figure>'
                     % (html.escape(SITE["url"] + p["cover"], quote=True),
                        html.escape(p["title"], quote=True)))
    if p.get("tldr"):
        parts.append("<h2>Коротко</h2><ul>%s</ul>"
                     % "".join("<li>%s</li>" % md_inline(x) for x in p["tldr"]))
    body = p["body"].strip()
    if body:
        parts.append(_feed_abs(md(link_articles_to_titles(body))))
    if p["sources"]:
        parts.append("<h2>Источники</h2><ol>%s</ol>" % "".join(
            '<li><a href="%s">%s</a></li>' % (html.escape(s["url"], quote=True), html.escape(s["name"]))
            if s["url"] else "<li>%s</li>" % html.escape(s["name"]) for s in p["sources"]))
    return "\n".join(x for x in parts if x)


def rss(posts, title=None, path="", self_name="rss.xml", limit=None, with_content=None,
        desc=None):
    """RSS 2.0: канал сайта (rss.xml), канал дайджестов (feed.xml) и лента автора.

    self-ссылка, lastBuildDate, рубрика, автор и полный текст — минимум, по
    которому лента считается живой и её берут агрегаторы.
    """
    limit = FEED_LIMIT if limit is None else limit
    with_content = FEED_FULL_TEXT if with_content is None else with_content
    items = []
    for p in posts[:limit]:
        url = "%s/%s%s.html" % (SITE["url"], path, p["slug"])
        author = AUTHOR_BY_CAT.get(p["category"])
        byline = (author["full_name"] or author["name"]) if author else SITE["author"]
        chunk = ['<title>%s</title>' % html.escape(p["title"]),
                 "<link>%s</link>" % url,
                 '<guid isPermaLink="true">%s</guid>' % url,
                 "<pubDate>%s</pubDate>" % rfc822(p["date"]),
                 "<dc:creator>%s</dc:creator>" % html.escape(byline),
                 "<category>%s</category>" % html.escape(CAT_NAME.get(p["category"]) or p["category"]),
                 "<description>%s</description>" % html.escape(p["summary"] or plain(p["body"], 300)),
                 _feed_cover(p)]
        full = _feed_html(p) if with_content else ""
        if full:
            chunk.append("<content:encoded>%s</content:encoded>" % html.escape(full))
        items.append("<item>%s</item>" % "".join(chunk))
    newest = max([p["date"] for p in posts] or [datetime.now()])
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" {ns}><channel><title>{title}</title><link>{url}/</link>
<description>{tag}</description><language>ru</language>
<copyright>© {title}</copyright>
<lastBuildDate>{built}</lastBuildDate>
<generator>GEEKOVSKI build.py</generator>
<atom:link href="{url}/{self_name}" rel="self" type="application/rss+xml"/>
<image><url>{url}/assets/img/icon-512.png</url><title>{title}</title><link>{url}/</link></image>
{items}</channel></rss>""".format(
        ns=RSS_NS, title=html.escape(title or SITE["title"]), url=SITE["url"],
        tag=html.escape(desc or SITE["tagline"]), built=rfc822(newest), self_name=self_name,
        items="".join(items))


# Полный текст в фиде ВК. False — фид остаётся анонсом (title + description +
# обложка), и импорт ВК делает карточку-ссылку на материал. True — в
# <content:encoded> уходит весь текст, и режим «Статья ВКонтакте» собирает
# статью целиком (цена — дубль контента и конкуренция с сайтом в поиске).
VK_FEED_FULL_TEXT = False

VK_PER_DAY = 3              # анонсов в сутки максимум
VK_PER_CAT_PER_DAY = 1      # и не больше одного из рубрики за сутки
VK_WINDOW_DAYS = 2          # окно фида: при первом включении импорта ВК
                            # подтянет только эти записи, а не весь архив
VK_FEED_LIMIT = 6


def vk_selection(posts, now=None):
    """Что из материалов уходит в ленту ВК.

    Приоритет: `vk: true` в frontmatter — берём всегда, `vk: false` — не берём
    никогда. Остальное добирает автоматика: свежие вперёд, не больше
    VK_PER_CAT_PER_DAY из одной рубрики за сутки и не больше VK_PER_DAY за
    сутки — стена молодого сообщества не должна читаться как спам.
    """
    now = now or datetime.now()
    floor = now - timedelta(days=VK_WINDOW_DAYS)
    picked, per_day, per_cat = [], collections.Counter(), collections.Counter()
    for p in sorted(posts, key=lambda x: x["date"], reverse=True):
        if p["kind"] != "post" or p["date"] < floor:
            continue
        flag = (p["meta"].get("vk") or "").strip().lower()
        if flag in ("false", "no", "0", "нет"):
            continue
        if flag in ("true", "yes", "1", "да"):
            picked.append(p)
            continue
        day = p["date"].date()
        if per_day[day] >= VK_PER_DAY or per_cat[(day, p["category"])] >= VK_PER_CAT_PER_DAY:
            continue
        picked.append(p)
        per_day[day] += 1
        per_cat[(day, p["category"])] += 1
    picked.sort(key=lambda x: x["date"], reverse=True)
    return picked[:VK_FEED_LIMIT]


def vk_feed(posts):
    """vk.xml — лента для штатного «Импорта RSS» сообщества ВКонтакте.

    ВК умеет сам переносить RSS на стену (Управление → Дополнительная
    информация → Импорт RSS), но берёт из фида всё подряд, без пауз и выбора.
    Поэтому для него собирается отдельный короткий фид: отбор делает сборка,
    ВК только переносит. content:encoded здесь нет намеренно — в режиме
    «Публиковать в виде статьи» ВК затащил бы на стену полный текст статьи
    дублем, а нам нужен анонс со сниппетом и обложкой.
    """
    return rss(vk_selection(posts), title="%s — для ВКонтакте" % SITE["title"],
               self_name="vk.xml", limit=VK_FEED_LIMIT,
               with_content=VK_FEED_FULL_TEXT)


DZEN_WINDOW_DAYS = 3
DZEN_FEED_LIMIT = 500


def dzen_selection(posts, now=None):
    """Only published articles from the last 72 hours; no archive backfill."""
    now = now or datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
    floor = now - timedelta(days=DZEN_WINDOW_DAYS)
    return sorted((p for p in posts if p["kind"] == "post" and not p["draft"]
                   and floor <= p["date"] <= now
                   and p["meta"].get("dzen", "true").lower() not in ("false", "no", "0", "нет")),
                  key=lambda p: p["date"], reverse=True)[:DZEN_FEED_LIMIT]


def dzen_image_allowed(url):
    path = local_image(url)
    if not path or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif"):
        return False
    size = image_size(path)
    if size is None and path.suffix.lower() == ".gif":
        try:
            data = path.read_bytes()[:10]
            if len(data) == 10 and data[:6] in (b"GIF87a", b"GIF89a"):
                size = struct.unpack("<HH", data[6:10])
        except OSError:
            pass
    return size is not None and size[0] >= 700


def dzen_feed(posts, now=None):
    """Dzen: automatic articles, noindex copies, stable canonical GUIDs."""
    selected = dzen_selection(posts, now)
    for prefix, uri in (("atom", "http://www.w3.org/2005/Atom"),
                        ("content", "http://purl.org/rss/1.0/modules/content/"),
                        ("dc", "http://purl.org/dc/elements/1.1/"),
                        ("media", "http://search.yahoo.com/mrss/")):
        ET.register_namespace(prefix, uri)
    root = ET.fromstring(rss(selected, self_name="dzen.xml", limit=DZEN_FEED_LIMIT,
                             with_content=True))
    for item in root.findall("./channel/item"):
        for category in item.findall("category"):
            item.remove(category)
        # No native-draft: the user explicitly chose immediate publication.
        for directive in ("format-article", "noindex"):
            ET.SubElement(item, "category").text = directive
        for media in list(item):
            if media.tag in ("enclosure", "{http://search.yahoo.com/mrss/}content"):
                if not dzen_image_allowed(media.get("url", "")):
                    item.remove(media)
        content = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        if content is not None:
            content.text = dzen_html(content.text or "", SITE["url"], dzen_image_allowed)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def sitemap(posts, digests=None, titles=None, with_calendar=False, authors=None, archive_keys=()):
    """Sitemap с lastmod у каждой записи и картинками материалов.

    lastmod без него поисковики перекачивают всё подряд; image:image пускает обложки
    в поиск по картинкам (в Яндексе это отдельная выдача).
    """
    def entry(loc, lastmod=None, image=None, caption=None):
        parts = ["<loc>%s</loc>" % html.escape(loc)]
        if lastmod:
            parts.append("<lastmod>%s</lastmod>" % lastmod)
        if image:
            parts.append('<image:image><image:loc>%s</image:loc>%s</image:image>'
                         % (html.escape(image), "<image:title>%s</image:title>" % html.escape(caption) if caption else ""))
        return "<url>%s</url>" % "".join(parts)

    urls = [entry(SITE["url"] + "/"), entry(SITE["url"] + CATEGORIES_PATH)]
    if archive_keys:
        urls.append(entry(SITE["url"] + "/archive/"))
        urls.extend(entry(SITE["url"] + archive_month_path(key)) for key in archive_keys)
    for c, _ in CATS:
        items = [p for p in posts if p["category"] == c]
        urls.append(entry(SITE["url"] + "/%s/" % c,
                          max([p["date"] for p in items]).strftime("%Y-%m-%d") if items else None))
    # /digests/ — служебная лента: в sitemap не ставим, у неё свой noindex

    urls.append(entry(SITE["url"] + "/about.html"))
    if with_calendar:
        urls.append(entry(SITE["url"] + "/calendar/"))
    # страницы редакции: люди, которые подписаны под материалами, — тоже точки входа
    if authors:
        urls.append(entry(SITE["url"] + "/avtory/"))
        for a in authors:
            urls.append(entry("%s/avtory/%s.html" % (SITE["url"], a["slug"]),
                              image=SITE["url"] + a["avatar"] if a["avatar"] else None,
                              caption=a["name"]))
    # страницы тайтлов (игры, фильмы, сериалы) — такие же точки входа, как материалы:
    # по ним ищут «<название> дата выхода», и из календаря на них ведут ссылки
    if titles:
        urls.append(entry(SITE["url"] + CATALOG_PATH))
    for slug in sorted(titles or {}):
        urls.append(entry(SITE["url"] + "/titles/" + slug + ".html"))
    for p in posts:
        if is_service(p):
            continue
        urls.append(entry("%s/%s.html" % (SITE["url"], p["slug"]),
                          (p.get("updated") or p["date"]).strftime("%Y-%m-%d"),
                          SITE["url"] + p["cover"] if p["cover"] else None, p["title"]))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">%s</urlset>'
            % "".join(urls))


def robots_txt():
    """Разрешаем всё, включая краулеры AI-поиска — иначе сайт не попадает в ответы.

    Отдельные User-agent не нужны (нет запретов), но перечисляем явно: часть площадок
    иначе считает, что её бот не приветствуется.
    """
    bots = ["YandexBot", "Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User",
            "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Amazonbot", "Applebot",
            "Applebot-Extended"]
    lines = ["# GEEKOVSKI — robots.txt", "User-agent: *", "Allow: /", ""]
    lines += ["User-agent: %s" % b for b in bots]
    lines += ["Allow: /", "", "Sitemap: %s/sitemap.xml" % SITE["url"],
              "Host: %s" % SITE["url"].split("//")[1], ""]
    return "\n".join(lines)


def llms_txt(posts, digests, titles=None, authors=None):
    """llms.txt по llmstxt.org: короткая карта сайта для языковых моделей.

    Не заменяет индексацию, но даёт LLM готовый список материалов со ссылками,
    датами и сутью — то, из чего собирается ответ со ссылкой на источник.
    Авторы идут отдельным разделом со своими лентами: по ним модель может взять
    материалы одного человека, а не весь канал целиком.
    """
    authors = AUTHORS if authors is None else authors
    out = ["# %s" % SITE["title"],
           "",
           "> %s. Разборы новостей игровой индустрии, техники, кино и AI: проверяемые факты, "
           "ссылки на первоисточники и даты. Русский язык." % SITE["tagline"],
           "",
           "## О сайте",
           "",
           "- Адрес: %s/" % SITE["url"],
           "- Язык: русский (ru-RU), часовой пояс материалов — MSK (UTC+3).",
           "- Формат: самостоятельные разборы новостей и дайджесты; у каждого материала "
           "перечислены источники, мнение автора помечено отдельно от факта.",
           "- Лента: %s/rss.xml (RSS), %s/feed.json (JSON), %s/sitemap.xml (sitemap)." % (
               SITE["url"], SITE["url"], SITE["url"]),
           "",
           "## Рубрики",
           ""]
    for c, name in CATS:
        items = [p for p in posts if p["category"] == c]
        out.append("- [%s](%s/%s/): %d %s" % (name, SITE["url"], c, len(items),
                                              plural(len(items), "материал", "материала", "материалов")))
    out += ["- [Дайджесты](%s/digests/): короткие выпуски новостей" % SITE["url"],
            "- [Календарь анонсов](%s/calendar/): подтверждённые даты релизов игр, фильмов и сериалов" % SITE["url"]]
    if authors:
        out += ["", "## Авторы", ""]
        for a in authors:
            full, _nick, _meta = _author_names(a)
            mine = author_posts(a, posts)
            out.append("- [%s](%s/avtory/%s.html): %s. %d %s; лента автора — %s/avtory/%s.xml" % (
                full, SITE["url"], a["slug"], a["role"], len(mine),
                plural(len(mine), "материал", "материала", "материалов"),
                SITE["url"], a["slug"]))
    out += ["", "## Материалы", ""]
    for p in posts:
        out.append("- [%s](%s/%s.html): %s (%s)" % (
            p["title"], SITE["url"], p["slug"], (p["summary"] or plain(p["body"], 160)).replace("\n", " "),
            p["date"].strftime("%d.%m.%Y")))
    if digests:
        out += ["", "## Дайджесты", ""]
        for d in digests:
            out.append("- [%s](%s/digests/%s.html): %s" % (
                d["title"], SITE["url"], d["slug"], (d["summary"] or "").replace("\n", " ")))
    if titles:
        out += ["", "## Тайтлы (страницы игр, фильмов и сериалов)", ""]
        for slug in sorted(titles):
            t = titles[slug]
            out.append("- [%s](%s/titles/%s.html)%s" % (
                t["title"], SITE["url"], slug,
                ": %s" % (t["meta"].get("year") or "") if t["meta"].get("year") else ""))
    out += ["", "## Служебное", "",
            "- [О сайте и правила редакции](%s/about.html)" % SITE["url"],
            "- [Полный текст всех материалов](%s/llms-full.txt)" % SITE["url"], ""]
    return "\n".join(out)


def llms_full_txt(posts):
    """Весь текст материалов одним файлом — для моделей, которым нужен корпус, а не карта."""
    out = ["# %s — полный текст" % SITE["title"], "",
           "Источник: %s. Лицензия на тексты — все права принадлежат %s; цитирование "
           "со ссылкой на страницу материала." % (SITE["url"], SITE["title"]), ""]
    for p in posts:
        out += ["---", "",
                "## %s" % p["title"], "",
                "- URL: %s/%s.html" % (SITE["url"], p["slug"]),
                "- Дата: %s" % p["date"].strftime("%d.%m.%Y %H:%M"),
                "- Рубрика: %s" % CAT_NAME.get(p["category"], p["category"]),
                "- Лид: %s" % (p["summary"] or plain(p["body"], 200)), ""]
        body = p["body"]
        body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)                     # картинки
        body = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", body)  # ссылки → текст
        out += [body.strip(), ""]
        if p["sources"]:
            out.append("Источники:")
            out += ["- %s — %s" % (s["name"], s["url"]) if s["url"] else "- %s" % s["name"]
                    for s in p["sources"]]
            out.append("")
    return "\n".join(out)


def parse_page(path: Path):
    """Простая страница (например, «О сайте»): frontmatter + markdown-тело."""
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, body.strip()


def render_about(theme):
    """AboutPage: для GEO это карточка сущности «кто здесь пишет и по каким правилам»."""
    path = ROOT / "content" / "about.md"
    if not path.exists():
        return None
    meta, body = parse_page(path)
    title = meta.get("title", "О сайте")
    desc = meta.get("summary") or plain(body, 160)
    content = ('<main class="wrap"><article class="post">'
               '<header class="post__head"><h1>%s</h1><p class="post__lead">%s</p></header>'
               '<div class="post__body">%s</div></article></main>'
               % (html.escape(title), html.escape(desc), md(body)))
    url = SITE["url"] + "/about.html"
    return page(title_tag(title), desc, content, theme, canonical=url, og_alt=title,
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "AboutPage", "@id": url + "#page", "url": url,
                               "name": title, "description": desc, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID},
                               "publisher": {"@id": ORG_ID},
                               "author": {"@id": ORG_ID}},
                              ld_breadcrumb([("Главная", "/"), (title, "/about.html")])))


def feed_json(posts):
    """JSON Feed 1.1: абсолютные ссылки, даты в ISO, обложка и источники.

    Такой фид читают агрегаторы и LLM без разбора HTML — карточка материала
    собирается из одного запроса.
    """
    return json.dumps({
        "version": "https://jsonfeed.org/version/1.1",
        "title": SITE["title"],
        "home_page_url": SITE["url"] + "/",
        "feed_url": SITE["url"] + "/feed.json",
        "description": SITE["tagline"],
        "language": "ru",
        "favicon": SITE["url"] + "/assets/img/icon-512.png",
        "items": [{
            "id": SITE["url"] + "/" + p["slug"] + ".html",
            "url": SITE["url"] + "/" + p["slug"] + ".html",
            "title": p["title"],
            "summary": p["summary"] or plain(p["body"], 240),
            "date_published": iso(p["date"]),
            "date_modified": iso(p.get("updated") or p["date"]),
            "tags": [CAT_NAME.get(p["category"], p["category"])],
            "image": SITE["url"] + p["cover"] if p["cover"] else None,
            "_sources": [{"name": s["name"], "url": s["url"]} for s in p["sources"] if s.get("url")],
        } for p in posts],
    }, ensure_ascii=False, indent=1)


def render_404(theme):
    content = ('<main class="wrap"><section class="lead"><h1>Страница не нашлась</h1>'
               '<p>Адрес мог измениться или в ссылке опечатка. Живые материалы — в рубриках '
               'и на <a href="/">главной</a>: '
               + ", ".join('<a href="/%s/">%s</a>' % (c, n) for c, n in CATS)
               + '.</p></section></main>')
    return page("Страница не найдена — %s" % SITE["title"],
                "Такой страницы нет. Свежие материалы GEEKOVSKI — на главной.",
                content, theme, robots="noindex,follow")


def image_report(posts):
    """Проверка повторов картинок до публикации.

    Две проблемы, которые реально случались: обложка стояла ещё и первым
    кадром в тексте, и один и тот же снимок уходил в две разные статьи.
    Здесь ловим первое и точное совпадение имени — быстро и без зависимостей.
    Визуально похожие кадры под разными именами ловит tools/imgcheck.py.
    """
    problems = []
    owners = {}
    for p in posts:
        body = re.findall(r"!\[[^\]]*\]\((/assets/img/[^)]+)\)", p["body"])
        ordered = ([p["cover"]] if p["cover"] else []) + body
        for url in ordered:
            if url and not (ROOT / "static" / url.replace("/assets/", "")).exists():
                problems.append("нет файла: %s — %s" % (p["slug"], url))
        for url, n in collections.Counter(u for u in ordered if u).items():
            if n > 1:
                problems.append("повтор в статье: %s — %s ×%d" % (p["slug"], url.split("/")[-1], n))
        for url in set(u for u in ordered if u):
            owners.setdefault(url.split("/")[-1], set()).add(p["slug"])
    for name, slugs in owners.items():
        if len(slugs) > 1:
            problems.append("в разных статьях: %s — %s" % (name, ", ".join(sorted(slugs))))
    return problems


# Старые адреса дайджестов, которые Google успел обнаружить в корне сайта.
LEGACY_DIGEST_SLUGS = {
    "2026-11-02-utro",
    "2026-11-03-vecher",
    "2026-11-05-otchet",
    "2026-11-05-vecher",
}


def redirect_page(path, label):
    url = SITE["url"] + path
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
        f'<title>{html.escape(label)} — GEEKOVSKI</title>'
        '<meta name="robots" content="noindex,follow">'
        f'<link rel="canonical" href="{html.escape(url, quote=True)}">'
        f'<meta http-equiv="refresh" content="0; url={html.escape(path, quote=True)}">'
        f'</head><body><p>Страница переехала: <a href="{html.escape(path, quote=True)}">'
        f'{html.escape(label)}</a></p></body></html>'
    )


def build(theme, out_dir, content_dir=None):
    global THEME_STYLESHEET
    content = Path(content_dir) if content_dir else ROOT / "content"
    everything = [parse_post(p) for p in sorted((content / "posts").glob("*.md"))]
    everything = [p for p in everything if not p["draft"]]
    everything.sort(key=lambda p: p["date"], reverse=True)
    posts = [p for p in everything if p["kind"] == "post"]
    months = archive_months(posts)
    digests = [p for p in everything if p["kind"] == "digest"]
    calendars = [p for p in everything if p["kind"] == "calendar"]
    cal_entries = calendar_entries(calendars)
    CAL_ENTRIES[:] = cal_entries
    TITLES.clear()
    TITLES.update(load_titles())
    configure_title_mentions()
    AUTHORS[:] = load_authors(content)
    AUTHOR_BY_CAT.clear()
    for a in AUTHORS:
        for c in a["categories"]:
            AUTHOR_BY_CAT.setdefault(c, a)
    ALL_POSTS[:] = posts + digests
    index_title_mentions(ALL_POSTS)

    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    scale = ROOT / "static" / "themes" / "_scale.css"
    theme_css = ROOT / "static" / "themes" / ("%s.css" % theme)
    parts = []
    if scale.exists():
        parts.append(scale.read_text(encoding="utf-8"))
    parts.append(theme_css.read_text(encoding="utf-8"))
    styles = "\n".join(parts).encode("utf-8")
    (out / "assets" / "theme.css").write_bytes(styles)
    version = hashlib.sha256(styles).hexdigest()[:12]
    THEME_STYLESHEET = f"/assets/theme.css?v={version}"
    for extra in (ROOT / "static" / "assets").glob("*") if (ROOT / "static" / "assets").exists() else []:
        shutil.copy(extra, out / "assets" / extra.name)
    fonts_src = ROOT / "static" / "fonts"
    if fonts_src.exists():
        (out / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
        for pattern in ("*.woff2", "*.ttf", "*-OFL.txt"):
            for f in fonts_src.glob(pattern):
                shutil.copy(f, out / "assets" / "fonts" / f.name)
        shutil.copy(ROOT / "static" / "fonts.css", out / "assets" / "fonts.css")
    img_src = ROOT / "static" / "img"
    if img_src.exists():
        (out / "assets" / "img").mkdir(parents=True, exist_ok=True)
        for img in img_src.glob("*"):
            if img.is_file():
                shutil.copy(img, out / "assets" / "img" / img.name)

    # Готовые сторонние страницы, живущие в корне сайта как есть (своя вёрстка,
    # свои шрифты, свой style.css). Кладём папку целиком: static/longreads/<slug>/
    # → docs/<slug>/. В ленту, sitemap, llms.txt и фиды они не попадают — вход
    # только по прямой ссылке; от индексации страницу держит её собственное
    # <meta name="robots" content="noindex"> (в robots.txt не закрываем: иначе
    # робот не прочитает noindex и покажет голый URL).
    longreads_src = ROOT / "static" / "longreads"
    if longreads_src.exists():
        for lr in sorted(p for p in longreads_src.iterdir() if p.is_dir()):
            shutil.copytree(lr, out / lr.name, dirs_exist_ok=True)

    open_rubrics.clear()
    for c, _n in CATS:
        open_rubrics[c] = len([p for p in posts if p["category"] == c])
    NAV_COUNTS["posts"] = len(posts)
    NAV_COUNTS["digests"] = len(digests)
    NAV_COUNTS["titles"] = len(TITLES)
    NAV_COUNTS["calendars"] = sum(1 for e in cal_entries if e["day"] >= datetime.now().date())
    (out / "index.html").write_text(render_index(posts, theme), encoding="utf-8")
    archive_dir = out / "archive"
    archive_dir.mkdir(exist_ok=True)
    (archive_dir / "index.html").write_text(render_archive(months, theme), encoding="utf-8")
    for key, items in months.items():
        month_dir = archive_dir / key
        month_dir.mkdir(exist_ok=True)
        (month_dir / "index.html").write_text(render_archive_month(key, items, theme), encoding="utf-8")
    for p in posts:
        (out / ("%s.html" % p["slug"])).write_text(render_post(p, posts, theme), encoding="utf-8")
    category_dir = out / CATEGORIES_PATH.strip("/")
    category_dir.mkdir(exist_ok=True)
    (category_dir / "index.html").write_text(render_categories(theme), encoding="utf-8")
    for c, name in CATS:
        d = out / c
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(render_cat(c, name, [p for p in posts if p["category"] == c], theme), encoding="utf-8")
    (out / "rss.xml").write_text(rss(posts), encoding="utf-8")
    (out / "dzen.xml").write_text(dzen_feed(posts), encoding="utf-8")
    # BOM перед декларацией: GitHub Pages отдаёт фид как application/xml без
    # charset, и парсеры (в первую очередь импортёр ВКонтакте) сваливаются в
    # windows-1251 — русские заголовки приезжают «РѕС‚Р±РёР»Р°СЃСЊ». BOM
    # заставляет читать поток как UTF-8. Для обычных читалок он безвреден.
    (out / "vk.xml").write_text("\ufeff" + vk_feed(posts), encoding="utf-8")
    dgdir = out / "digests"
    dgdir.mkdir(exist_ok=True)
    (dgdir / "index.html").write_text(render_digests_index(digests, theme), encoding="utf-8")
    for i, d in enumerate(digests):
        nxt = digests[i - 1] if i > 0 else None      # новее
        prv = digests[i + 1] if i + 1 < len(digests) else None
        (dgdir / ("%s.html" % d["slug"])).write_text(render_digest(d, theme, nxt, prv), encoding="utf-8")
        if d["slug"] in LEGACY_DIGEST_SLUGS:
            (out / f'{d["slug"]}.html').write_text(
                redirect_page(publication_path(d), d["title"]), encoding="utf-8")
    tdir = out / "titles"
    tdir.mkdir(exist_ok=True)
    (tdir / "index.html").write_text(render_catalog(TITLES, cal_entries, theme), encoding="utf-8")
    for slug in TITLES:
        htmlp = title_page(slug, theme)
        if htmlp:
            (tdir / ("%s.html" % slug)).write_text(htmlp, encoding="utf-8")
    for old_slug, slug in TITLE_REDIRECTS.items():
        (tdir / f"{old_slug}.html").write_text(
            redirect_page(f"/titles/{slug}.html", TITLES[slug]["title"]), encoding="utf-8")
    if AUTHORS:
        adir = out / "avtory"
        adir.mkdir(exist_ok=True)
        (adir / "index.html").write_text(render_authors_index(AUTHORS, theme), encoding="utf-8")
        for a in AUTHORS:
            (adir / ("%s.html" % a["slug"])).write_text(author_page(a, posts, theme), encoding="utf-8")
        # лента автора лежит рядом с его страницей: /avtory/<slug>.xml
        for a in AUTHORS:
            (adir / ("%s.xml" % a["slug"])).write_text(
                author_feed(a, author_posts(a, posts)), encoding="utf-8")
    # файл календаря живёт в content/posts, но собственной страницы у него нет:
    # его slug мог попасть в закладки и в поиск — отдаём редирект на общий раздел
    for c in calendars:
        (out / ("%s.html" % c["slug"])).write_text(
            redirect_page("/calendar/", "Календарь анонсов"), encoding="utf-8")
    cdir = out / "calendar"
    cdir.mkdir(exist_ok=True)
    (cdir / "index.html").write_text(render_calendar_page(cal_entries, theme), encoding="utf-8")
    (out / "style-guide.html").write_text(render_style_guide(theme), encoding="utf-8")
    (out / "404.html").write_text(render_404(theme), encoding="utf-8")
    about = render_about(theme)
    if about:
        (out / "about.html").write_text(about, encoding="utf-8")
    (out / "manifest.webmanifest").write_text(json.dumps({
        "name": "GEEKOVSKI — игры, техника, кино",
        "short_name": "GEEKOVSKI",
        "description": "Разборы и новости игр, техники, кино и AI с источниками.",
        "lang": "ru",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": THEME_COLORS.get(theme, "#0A0C0F"),
        "theme_color": THEME_COLORS.get(theme, "#0A0C0F"),
        "icons": [
            {"src": "/assets/img/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/assets/img/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "/assets/img/favicon-192.png", "sizes": "192x192", "type": "image/png"},
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    worker = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    worker = worker.replace('"/assets/theme.css"', json.dumps(THEME_STYLESHEET))
    (out / "sw.js").write_text(worker, encoding="utf-8")
    (out / "offline.html").write_text(offline_page(theme), encoding="utf-8")
    (out / "robots.txt").write_text(robots_txt(), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(posts, digests, TITLES, AUTHORS), encoding="utf-8")
    (out / "llms-full.txt").write_text(llms_full_txt(posts), encoding="utf-8")
    (out / "feed.xml").write_text(rss(digests, title="%s — дайджесты" % SITE["title"], path="digests",
                                     self_name="feed.xml"), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(posts, digests, TITLES, with_calendar=bool(cal_entries),
                                            authors=AUTHORS, archive_keys=months),
                                     encoding="utf-8")
    (out / "feed.json").write_text(feed_json(posts), encoding="utf-8")
    ico = ROOT / "static" / "img" / "favicon.ico"
    if ico.exists():
        shutil.copy(ico, out / "favicon.ico")
    # IndexNow: ключ должен лежать файлом <ключ>.txt в корне сайта, иначе пинг отклонят
    keyfile = ROOT / "static" / "indexnow-key.txt"
    if keyfile.exists():
        k = keyfile.read_text(encoding="utf-8").strip()
        (out / ("%s.txt" % k)).write_text(k, encoding="utf-8")
    (out / ".nojekyll").write_text("")
    if (ROOT / "static" / "CNAME").exists():
        shutil.copy(ROOT / "static" / "CNAME", out / "CNAME")
    return posts




# ---------- Календарь анонсов ----------

MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]


PLATFORMS = {
    "switch2": ("Switch 2", "switch"), "switch": ("Switch", "switch"),
    "ps5": ("PS5", "playstation"), "ps4": ("PS4", "playstation"),
    "xbox": ("Xbox Series", "xbox"), "pc": ("PC", "pc"), "mac": ("Mac", "pc"),
    "vr": ("VR", "vr"), "netflix": ("Netflix", "serialy"), "prime": ("Prime Video", "serialy"), "hbo": ("HBO Max", "serialy"), "kino": ("Кино", "kino"),
    "tv": ("ТВ", "serialy"),
}


CATALOG_PATH = "/titles/"
TITLE_KINDS = {
    "game": ("Игра", "Игры"),
    "film": ("Фильм", "Кино"),
    "series": ("Сериал", "Сериалы"),
    "gadget": ("Гаджет", "Гаджеты"),
}


def release_date(day):
    return f"{day.day} {MONTHS_GEN[day.month - 1]} {day.year}"


def platform_text(platforms):
    readable = {"pc": "ПК", "kino": "Кинотеатры"}
    return " · ".join(readable.get(token, PLATFORMS.get(token, (token, ""))[0])
                      for token in platforms.split())


def collection_cover(src):
    # Старые шаблонные обложки календаря содержат повторяющиеся дату и заголовок.
    path = local_image(urllib.parse.urljoin(SITE["url"], src))
    if not src or not path or path.name.startswith("anno-") or not path.is_file():
        return ""
    return src


def card_credit(value):
    label, separator, url = value.rpartition("|")
    if separator and urllib.parse.urlsplit(url.strip()).scheme in ("https", "http"):
        return f'<p>Фото: <a href="{html.escape(url.strip())}">{html.escape(label.strip())}</a></p>'
    return ""


def collection_card(title, url, summary, meta, *, cover="", facts="", details="",
                    links="", attrs="", priority=False):
    cover = collection_cover(cover)
    image = image_tag(cover, priority=priority).replace("<img ", '<img class="collection-card__cover" ', 1)
    facts = f'<p class="collection-card__facts">{html.escape(facts)}</p>' if facts else ""
    summary = f'<p class="collection-card__summary">{html.escape(summary)}</p>' if summary else ""
    links = f'<div class="collection-card__links">{links}</div>' if links else ""
    return (f'<article class="collection-card" data-collection-item{attrs}>'
            f'{image}<div class="collection-card__text"><p class="collection-card__meta">{meta}</p>'
            f'<h3><a href="{html.escape(url)}">{html.escape(title)}</a></h3>'
            f'{facts}{summary}{details}</div>{links}</article>')


def collection_filters(name, choices, label):
    buttons = "".join(
        f'<button type="button" data-filter-value="{html.escape(value)}"'
        f' aria-pressed="{str(index == 0).lower()}">{html.escape(text)}</button>'
        for index, (value, text) in enumerate(choices)
    )
    return (f'<div class="collection-filters collection-filters--{name}" data-filter="{name}"'
            f' role="group" aria-label="{label}">{buttons}</div>')


def month_filter(days):
    keys = sorted({day.strftime("%Y-%m") for day in days}, reverse=True)
    options = "".join(f'<option value="{key}">{archive_month_name(key)}</option>' for key in keys)
    return ('<label class="collection-field">Месяц <select data-filter="month">'
            f'<option value="">Все месяцы</option>{options}</select></label>')


def collection_layout(title, count_name, controls, cards, *, mode="", empty):
    path = "/titles/" if mode == "catalog" else f"/{mode}/"
    classes = ' collection-grid--digests' if mode == 'digests' else ''
    return (
        f'<main class="wrap collection" data-collection="{mode}">'
        + breadcrumbs([("Блог", "/"), (title, path)])
        + f'<h1>{title}</h1><div class="collection-controls" data-collection-controls hidden>{controls}</div>'
        f'<div class="collection-heading"><h2>{count_name}</h2><span data-collection-count role="status"></span></div>'
        f'<div class="collection-grid{classes}">{cards}</div>'
        f'<p class="collection-empty" data-collection-empty{" hidden" if cards else ""}>{empty}</p></main>'
    )


def collection_assets():
    assets = ROOT / "static" / "assets"
    version = hashlib.sha256((assets / "collections.css").read_bytes()
                             + (assets / "collections.js").read_bytes()).hexdigest()[:10]
    return (f'<link rel="stylesheet" href="/assets/collections.css?v={version}">'
            f'<script defer src="/assets/collections.js?v={version}"></script>')


def render_calendar_page(entries, theme, today=None):
    today = today or datetime.now(timezone(timedelta(hours=3))).date()
    upcoming = [entry for entry in entries if entry["day"] >= today]
    recent = list(reversed([entry for entry in entries if entry["day"] < today]))
    cards = []
    for index, entry in enumerate(upcoming + recent):
        day = entry["day"]
        title = TITLES.get(entry["slug"], {})
        cover = collection_cover(entry["cover"]) or title.get("cover") or ""
        kind = (title.get("kind") or
                {"kino": "film", "serialy": "series", "gadgets": "gadget"}.get(entry["category"], "game"))
        period = "past" if day < today else "week" if (day - today).days <= 6 else "later"
        meta = (f'<time datetime="{day.isoformat()}">{release_date(day)}</time> · '
                f'{TITLE_KINDS[kind][0]} · {html.escape(entry["kind_note"] or "релиз")}')
        summary = title.get("card_summary") or plain(entry["summary"], 155)
        more = f'<p>{html.escape(entry["summary"])}</p>' if entry["summary"] != summary and entry["summary"] else ""
        more += card_credit(title.get("cover_source", ""))
        details = f'<details><summary>Подробнее</summary>{more}</details>' if more else ""
        links = (f'<a href="{CATALOG_PATH}#title-{html.escape(entry["slug"])}">В каталог ↗</a>'
                 if title else "")
        for reference in entry["source"].split(";"):
            source, separator, url = reference.rpartition("|")
            if separator and urllib.parse.urlsplit(url.strip()).scheme in ("https", "http"):
                links += f'<a href="{html.escape(url.strip())}">{html.escape(source.strip())} ↗</a>'
        facts = " · ".join(value for value in (platform_text(entry["platforms"]), entry["where"]) if value)
        cards.append(collection_card(entry["title"], entry["href"], summary, meta, cover=cover,
                                     facts=facts, details=details, links=links, priority=index < 3,
                                     attrs=f' data-kind="{kind}" data-period="{period}"'))
    controls = collection_filters("period", [("week", "Ближайшие 7 дней"), ("later", "Позже"),
                                            ("past", "Уже вышло")], "Период")
    controls += collection_filters("kind", [("", "Все")] + [(k, v[1]) for k, v in TITLE_KINDS.items()],
                                   "Тип релиза")
    content = collection_layout("Календарь релизов", "Расписание", controls, "".join(cards),
                                mode="calendar", empty="В этом периоде пока нет релизов выбранной категории.")
    desc = "Календарь выхода игр, фильмов, сериалов и гаджетов. Даты, платформы, регионы и ссылки на источники."
    url = SITE["url"] + "/calendar/"
    return page(title_tag("Календарь релизов"), desc, content, theme, canonical=url,
                head_extra=collection_assets(),
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": "Календарь релизов", "description": desc, "isPartOf": {"@id": WEBSITE_ID}},
                              calendar_itemlist(upcoming),
                              ld_breadcrumb([("Блог", "/"), ("Календарь релизов", "/calendar/")])))


def render_catalog(titles, entries, theme):
    events = collections.defaultdict(list)
    today = datetime.now(timezone(timedelta(hours=3))).date()
    for entry in entries:
        events[entry["slug"]].append(entry)
    chosen = {}
    for slug, days in events.items():
        chosen[slug] = next((e for e in days if e["day"] >= today), days[-1])
    items = sorted(titles.values(), key=lambda item: (
        not bool(collection_cover(item["cover"])),
        chosen[item["slug"]]["day"] if item["slug"] in chosen and chosen[item["slug"]]["day"] >= today
        else datetime.max.date(),
        item["title"].casefold(),
    ))
    cards, ld_items = [], []
    for index, item in enumerate(items, 1):
        slug = item["slug"]
        url = f"{CATALOG_PATH}{slug}.html"
        event = chosen.get(slug)
        if event:
            day = event["day"]
            timing = f'<time datetime="{day.isoformat()}">{release_date(day)}</time>'
        else:
            timing = html.escape(item["year"])
        label = TITLE_KINDS[item["kind"]][0]
        meta = " · ".join(filter(None, (html.escape(label), timing)))
        facts = " · ".join(filter(None, (item["meta"].get("brand"), platform_text(item["platforms"]))))
        credit = card_credit(item["cover_source"])
        details = f'<details><summary>Об изображении</summary>{credit}</details>' if credit else ""
        search = html.escape(" ".join(_aliases(item)), quote=True)
        cards.append(collection_card(item["title"], url, item["card_summary"] or plain(item["body"], 145),
                                     meta, cover=item["cover"], facts=facts, details=details, priority=index <= 3,
                                     links=f'<a href="{html.escape(url)}">Открыть карточку ↗</a>',
                                     attrs=f' id="title-{html.escape(slug)}" data-kind="{item["kind"]}" data-search="{search}"'))
        ld_items.append({"@type": "ListItem", "position": index, "url": SITE["url"] + url, "name": item["title"]})
    controls = collection_filters("kind", [("", "Все")] + [(k, v[1]) for k, v in TITLE_KINDS.items()], "Тип релиза")
    controls += ('<label class="collection-field">Поиск <input type="search" data-collection-search'
                 ' placeholder="По названию"></label>')
    content = collection_layout("Каталог", "Карточки", controls, "".join(cards),
                                mode="catalog", empty="По этому запросу ничего не найдено.")
    url = SITE["url"] + CATALOG_PATH
    desc = "Каталог игр, фильмов, сериалов и гаджетов GEEKOVSKI. Описания, даты релизов, платформы и связанные публикации."
    return page(title_tag("Каталог игр, фильмов, сериалов и гаджетов"), desc, content, theme, canonical=url,
                head_extra=collection_assets(),
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url, "name": "Каталог",
                               "description": desc, "isPartOf": {"@id": WEBSITE_ID}},
                              {"@type": "ItemList", "numberOfItems": len(ld_items), "itemListElement": ld_items},
                              ld_breadcrumb([("Блог", "/"), ("Каталог", CATALOG_PATH)])))


def calendar_itemlist(entries, limit=30):
    """Даты релизов списком: машиночитаемый ответ на «когда выходит X»."""
    upcoming = sorted(entries, key=lambda e: e["day"])[:limit]
    if not upcoming:
        return None
    return {
        "@type": "ItemList", "name": "Ближайшие релизы", "numberOfItems": len(upcoming),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "url": SITE["url"] + e["href"],
             "name": e["title"],
             "description": e["day"].strftime("%d.%m.%Y")}
            for i, e in enumerate(upcoming)
        ],
    }


TRANSLIT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
            "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
            "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
            "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}


def published_index():
    """Индекс уже вышедших материалов для проверки на дубли: слаг, заголовок,
    дата и текст. Читается из content/posts, чтобы проверка была дешёвой."""
    out = []
    for f in sorted((ROOT / "content" / "posts").glob("*.md")):
        t = f.read_text(encoding="utf-8")
        title = ""
        date = ""
        for line in t.split("\n")[:20]:
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            elif line.startswith("date:"):
                date = line.split(":", 1)[1].strip()
        if title:
            out.append({"slug": f.stem, "title": title, "date": date[:10],
                        "words": len(t.split())})
    return out


def topic_duplicates(topics, lookback_days=7, max_df=8):
    """Проверка СПИСКА ТЕМ перед отправкой автору.

    Сравнения по заголовку мало: «Бегущий по лезвию 2099: всё, что известно»
    и «7 сериалов ноября» не делят ни одного слова из названия темы, хотя это
    один и тот же материал. Поэтому тема сверяется с заголовком, summary и
    началом тела по «якорям» — латинским названиям, числам от трёх цифр и
    редким русским словам. Редкость считается по всему архиву: слово,
    которое встречается в 10 постах («ноября», «премьера»), якорем не бывает.
    """
    import re as _re

    def raw_anchors(s):
        latin = _re.findall(r"[A-Za-z][A-Za-z0-9'’-]{2,}", s)
        nums = _re.findall(r"\b\d{3,}\b", s)
        cyr = [w for w in _re.findall(r"[А-Яа-яЁё]{6,}", s)]
        return {w.lower() for w in latin + nums + cyr}

    posts = []
    df = {}
    for f in sorted((ROOT / "content" / "posts").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = _re.search(r"^title:\s*(.+)$", text, _re.M)
        title = m.group(1) if m else ""
        head = "\n".join(text.split("\n")[:12])
        body = text.split("---", 2)[-1][:1500]
        seen = raw_anchors(head) | raw_anchors(body)
        posts.append((f.stem, title, head, body))
        for w in seen:
            df[w] = df.get(w, 0) + 1

    out = []
    for t in topics:
        ta = {w for w in raw_anchors(t) if df.get(w, 0) <= max_df}
        best = None
        for slug, title, head, body in posts:
            for part, weight in ((head, 1.0), (body, 0.7)):
                shared = ta & {w for w in raw_anchors(part) if df.get(w, 0) <= max_df}
                letters = {w for w in shared if not w.isdigit()}
                if (len(letters) >= 2 or (len(letters) >= 1 and len(shared) >= 2)) \
                        and (best is None or weight > best[0]):
                    best = (weight, slug, title, sorted(shared))
        out.append((t, best))
    return out


def is_duplicate(topic, posts_index, lookback_days=7):
    """Грубая, но честная проверка на дубль: доля общих значимых слов заголовка
    с любым материалом за N дней. 0.6 и выше — дубль."""
    import re as _re
    stop = {"и", "в", "на", "с", "по", "для", "из", "о", "как", "что", "это",
            "the", "a", "of", "to", "in", "and", "for"}
    def words(s):
        return {w for w in _re.findall(r"[а-яёa-z0-9]+", s.lower())
                if w not in stop and len(w) > 2}
    tw = words(topic)
    if not tw:
        return None
    best = None
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    for p in posts_index:
        if p["date"] and p["date"] < cutoff:
            continue
        sw = words(p["title"])
        if not sw:
            continue
        share = len(tw & sw) / len(tw)
        if share >= 0.6 and (best is None or share > best[0]):
            best = (share, p)
    return best


def title_slug(text):
    s = "".join(TRANSLIT.get(ch, ch) for ch in (text or "").lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "title"


TITLE_REDIRECTS = {"gta-6": "grand-theft-auto-vi"}
TITLES = {}
TITLE_ALIASES = {}
TITLE_MENTION_PATTERN = None
TITLE_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(/titles/([a-z0-9-]+)\.html\)")
TITLE_ARTICLES = collections.defaultdict(list)
ALL_POSTS = []
CAL_ENTRIES = []   # заполняется в build(): записи календаря для страниц тайтлов
AUTHORS = []       # заполняется в build(): паспорта редакции из content/authors
AUTHOR_BY_CAT = {}  # рубрика → паспорт автора, который её ведёт


def load_titles():
    """Карточки релизов из content/titles, по одной на постоянный адрес."""
    out = {}
    d = ROOT / "content" / "titles"
    if not d.exists():
        return out
    for f in sorted(d.glob("*.md")):
        rec = parse_post(f)          # frontmatter + текст как summary-тело
        slug = rec["slug"] if rec.get("slug") else f.stem
        out[slug] = {
            "slug": slug,
            "kind": rec["kind"] if rec["kind"] in TITLE_KINDS else "game",
            "title": rec["title"],
            "year": rec["meta"].get("year", ""),
            "genre": rec["meta"].get("genre", ""),
            "developers": rec["meta"].get("developer", ""),
            "platforms": rec["meta"].get("platforms", ""),
            "links": rec["meta"].get("links", ""),
            "cover": rec["cover"],
            "card_summary": rec["meta"].get("card_summary", ""),
            "cover_source": rec["meta"].get("cover_source", ""),
            "body": rec["body"],
            "sources": rec["sources"],
            "meta": rec["meta"],
            "aliases": rec["meta"].get("aliases", ""),
        }
    return out


def title_page(slug, theme):
    t = TITLES.get(slug)
    if not t:
        return None
    plat_labels = " · ".join(PLATFORMS.get(p, (p, ""))[0] for p in (t["platforms"] or "").split())
    if t["kind"] == "game":
        rows = [("Год", t["year"]), ("Разработчик", t["developers"]),
                ("Издатель", t["meta"].get("publisher", "")), ("Жанр", t["genre"]),
                ("Платформы", plat_labels)]
    elif t["kind"] == "gadget":
        rows = [("Год", t["year"]), ("Бренд", t["meta"].get("brand", "")), ("Тип", t["genre"])]
    else:
        rows = [("Год", t["year"]), ("Студия", t["developers"]),
                ("Дистрибьютор", t["meta"].get("publisher", "")), ("Жанр", t["genre"]),
                ("Где смотреть", plat_labels)]
    meta = "".join('<div class="tp__row"><span class="tp__k">%s</span><span class="tp__v">%s</span></div>'
                   % (k, html.escape(v)) for k, v in rows if v)
    srcs = "".join('<li><a href="%s">%s</a></li>' % (x["url"], html.escape(x["name"]))
                   for x in t["sources"] if x["url"])
    cover = ('<div class="tp__cover"><img src="%s" alt="%s"></div>'
             % (t["cover"], html.escape(t["title"], quote=True))) if t["cover"] else ""
    events = [entry for entry in CAL_ENTRIES if entry["slug"] == slug]
    rel = [e for e in events if e["day"] >= datetime.now(timezone(timedelta(hours=3))).date()]
    when = ""
    if rel:
        e = sorted(rel, key=lambda x: x["day"])[0]
        when = ('<div class="tp__when">Выходит <b>%d %s</b></div>'
                % (e["day"].day, MONTHS_GEN[e["day"].month - 1]))
    schedule = ""
    if events:
        rows = []
        for entry in events:
            day = entry["day"]
            place = " · ".join(filter(None, (platform_text(entry["platforms"]), entry["where"])))
            rows.append(f'<li><time datetime="{day.isoformat()}">{release_date(day)}</time> — '
                        f'{html.escape(entry["kind_note"] or "релиз")}{html.escape(" · " + place) if place else ""}</li>')
        schedule = '<section class="sources"><h2>Даты релизов</h2><ul>' + "".join(rows) + '</ul></section>'
    credit = card_credit(t["cover_source"])
    mentions = TITLE_ARTICLES.get(slug)
    if mentions:
        if len(mentions) == 1 and mentions[0]["kind"] == "post":
            m = mentions[0]
            ment_block = ('<section class="related"><h2>Упоминается в статье</h2>'
                          '<a class="mnews" href="/%s.html"><span class="mnews__t">%s</span>'
                          '<span class="mnews__d">%s</span></a></section>') % (
                m["slug"], html.escape(m["title"]), m["date"].strftime("%d.%m.%Y"))
        else:
            rows = []
            for m in mentions:
                if m["kind"] == "digest":
                    href = "/digests/%s.html" % m["slug"]
                    label = m["title"]
                    date = m["date"].strftime("%d.%m.%Y")
                else:
                    href = "/%s.html" % m["slug"]
                    label = m["title"]
                    date = m["date"].strftime("%d.%m.%Y")
                rows.append('<a class="mnews" href="%s"><span class="mnews__t">%s</span>'
                            '<span class="mnews__d">%s</span></a>' % (href, html.escape(label), date))
            ment_block = ('<section class="related"><h2>Упоминается в %d %s</h2>%s</section>'
                          % (len(mentions), plural(len(mentions), "материале", "материалах", "материалах"),
                             "".join(rows)))
    else:
        ment_block = ""
    content = ('<main class="wrap"><article class="tp">%s<h1>%s</h1>%s'
               '<div class="tp__meta">%s</div><div class="post__body">%s</div>%s'
               '%s</article>%s</main>') % (
        cover, html.escape(t["title"]), when, meta, md(t["body"]) if t["body"] else "",
        schedule + (('<section class="sources"><h2>Источники</h2><ul>%s</ul>%s</section>' % (srcs, credit))
                    if srcs or credit else ""),
        share_block(SITE["url"] + "/titles/%s.html" % slug, t["title"], t["cover"] or DEFAULT_OG),
        ment_block)
    content = content.replace('<main class="wrap"><article class="tp">',
                              '<main class="wrap">' + back_link("К каталогу", CATALOG_PATH) + '<article class="tp">', 1)
    return page("%s — %s | %s" % (t["title"], TITLE_KINDS[t["kind"]][0].lower(),
                                  SITE["title"]),
                plain(t["body"], 180), content, theme,
                canonical=SITE["url"] + "/titles/%s.html" % slug,
                og_image=t["cover"] or DEFAULT_OG,
                jsonld=ldjson(ld_org(), ld_website(), ld_title(t, slug),
                              ld_breadcrumb([("Главная", "/"), ("Каталог", CATALOG_PATH),
                                             (t["title"], "/titles/%s.html" % slug)])))


def ld_title(t, slug):
    """Разметка страницы тайтла: VideoGame / Movie / TVSeries.

    Именно на такие страницы опирается ответ «когда выходит <название>»:
    в разметке есть дата релиза из календаря, жанр, студия и издатель.
    """
    url = "%s/titles/%s.html" % (SITE["url"], slug)
    kind = {"game": "VideoGame", "film": "Movie", "series": "TVSeries", "gadget": "Product"}[t["kind"]]
    obj = {"@type": kind, "@id": url + "#entity", "name": t["title"], "url": url,
           "inLanguage": "ru-RU", "description": plain(t["body"], 200) or None}
    if t["cover"]:
        entry = {"@type": "ImageObject", "url": SITE["url"] + t["cover"]}
        size = image_size(local_image(SITE["url"] + t["cover"]) or Path("/nonexistent"))
        if size:
            entry["width"], entry["height"] = size
        obj["image"] = entry
    if t["kind"] == "gadget":
        obj["brand"] = t["meta"].get("brand") or None
        obj["category"] = t["genre"] or None
    elif t["genre"]:
        obj["genre"] = [g.strip() for g in re.split(r"[,/]", t["genre"]) if g.strip()]
    for key, meta_key in (("productionCompany", "developer"), ("publisher", "publisher")):
        name = (t.get("meta") or {}).get(meta_key) or t["developers"]
        if name:
            obj[key] = {"@type": "Organization", "name": name}
    # подтверждённая дата релиза из календаря (ближайшая будущая или последняя прошедшая)
    days = sorted(e["day"] for e in CAL_ENTRIES if e.get("slug") == slug)
    if days and t["kind"] != "gadget":
        today = datetime.now(timezone(timedelta(hours=3))).date()
        future = [d for d in days if d >= today]
        obj["datePublished"] = (future[0] if future else days[-1]).strftime("%Y-%m-%d")
    return {k: v for k, v in obj.items() if v is not None}


def calendar_entries(calendars):
    """Разворачивает заметки kind: calendar в плоский список записей."""
    out, seen = [], set()
    for c in calendars:
        for it in c["items"]:
            day = None
            try:
                day = datetime.strptime(it.get("date", ""), "%Y-%m-%d").date()
            except ValueError:
                continue
            slug = it.get("slug") or title_slug(it["title"])
            slug = TITLE_REDIRECTS.get(slug, slug)
            key = (day, slug, it.get("platforms", ""), it.get("kind_note", ""), it.get("where", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "day": day, "category": it["category"], "title": it["title"],
                "cover": it.get("cover", ""),
                "slug": slug,
                "platforms": it.get("platforms", ""), "kind_note": it.get("kind_note", ""),
                "summary": it["summary"], "source": it["source"], "where": it.get("where", ""),
                "href": "/titles/%s.html" % slug,
            })
    out.sort(key=lambda e: (e["day"], e["title"]))
    return out


# ---------- Style Guide ----------

def _swatch(name, var, note=""):
    return ('<div class="sg-swatch"><span class="sg-swatch__chip" style="background:%s"></span>'
            '<span class="sg-swatch__name">%s</span><span class="sg-swatch__hex">%s</span>'
            '<span class="sg-swatch__note">%s</span></div>' % (var, name, var, note))


def render_style_guide(theme):
    months = ["ВЕЧЕР", "УТРО"]
    rows = []
    editorial = theme == "editorial"
    display_family = "Sofia Sans Extra Condensed" if editorial else "Random Grotesque Spacious"
    text_family = "Golos Text" if editorial else "Medeo Sans"
    label_family = "Golos Text" if editorial else "Chava"

    # --- типографика
    type_rows = [
        ("H0 · заголовок статьи", "h0", f"var(--fs-h0) · 52 px · {display_family}", "Убыток Anthropic и Crimson Desert на PS5"),
        ("H1 · герой, H2 в тексте", "h1", "var(--fs-h1) · 40 px", "Ocarina of Time выходит 5 ноября"),
        ("H2 · карточки, H3 в тексте", "h2", "var(--fs-h2) · 24 px", "Pikmin 4: демо уже в eShop"),
        ("Лид", "lead-text", f"var(--fs-lead) · 17 px · {text_family}", "Демо Pikmin 4 в eShop, Zelda выходит 5 ноября, Circana зафиксировала падение продаж."),
        ("Основной текст", "body-text", f"var(--fs-body) · 16 px · {text_family}", "Nintendo провела Pikmin Direct, предупредив за десять минут до эфира."),
        ("Мелкий текст", "small-text", "var(--fs-small) · 14 px", "Стартовая зона и два экзамена Dandori Academy"),
        ("Метка", "meta-text", f"var(--fs-meta) · 12 px · {label_family}", "NINTENDO SWITCH · 3 НОЯБРЯ"),
    ]
    for label, cls, spec, sample in type_rows:
        rows.append('<div class="sg-row"><div class="sg-row__label">%s<br><code>%s</code></div>'
                    '<div class="sg-row__demo"><div class="%s">%s</div>'
                    '<div class="sg-row__spec">%s</div></div></div>' % (label, spec, cls, sample, spec))
    type_block = '<section class="sg-block"><h2>Типографика</h2>%s</section>' % "".join(rows)

    # --- палитра
    palette = [
        ("ink", "#0A0C0F", "фон"), ("panel", "#11151A", "плашки"), ("line", "#1F252E", "разделители"),
        ("text", "#E9EBEE", "основной текст"), ("muted", "#8B939E", "второй план"),
        ("accent", "#377BF0", "акцент (синий из логотипа)"),
    ]
    if editorial:
        palette = [("bg", "#F1F4F9", "фон"), ("panel", "#FBFCFE", "панели"), ("line", "#C1CCDF", "разделители"),
                   ("text", "#152B50", "основной текст"), ("muted", "#4A5D7B", "второй план"),
                   ("accent", "#214FBD", "акцент")]
    cats = [("Xbox", "#2FB344"), ("Nintendo Switch", "#E60012"), ("PlayStation", "#2F6DF6"),
            ("PC-игры", "#8B5CF6"), ("VR", "#A855F7"), ("Гаджеты", "#22D3EE"),
            ("Кино", "#F0553F"), ("Сериалы", "#F5A524"), ("AI", "#14B8A6")]
    slots = [("Утро", "#F5C518", "жёлтый"), ("Вечер", "#A855F7", "фиолетовый")]
    palette_block = ('<section class="sg-block"><h2>Палитра</h2><div class="sg-grid">%s</div>'
                     '<h3>Рубрики</h3><div class="sg-grid">%s</div>'
                     '<h3>Время суток в дайджестах</h3><div class="sg-grid">%s</div></section>') % (
        "".join(_swatch(n, h, note) for n, h, note in palette),
        "".join(_swatch(n, h) for n, h in cats),
        "".join(_swatch(n, h, note) for n, h, note in slots))

    # --- чипы
    chips = "".join('<span class="chip cat-%s">%s</span>' % (c, name) for c, name in
                    [("switch", "Nintendo Switch"), ("ai", "AI"), ("gadgets", "Гаджеты"), ("kino", "Кино")])
    chip_block = ('<section class="sg-block"><h2>Теги</h2><div class="sg-demo">%s '
                  '<span class="chip chip--solid">Дайджест</span></div>'
                  '<p class="sg-hint">%s · 12 px</p></section>') % (chips, label_family)

    # --- иконки рубрик
    icons = "".join('<div class="sg-icon"><span class="ditem__icon cat-%s">%s</span><span>%s</span></div>'
                    % (c, ICONS.get(c, ""), name) for c, name in CATS)
    icon_block = ('<section class="sg-block"><h2>Иконки рубрик</h2><div class="sg-icons">%s</div>'
                  '<p class="sg-hint">Инлайн-SVG 24×24, цвет наследуется от рубрики. Иконки бренда:</p>'
                  '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:16px;margin-top:8px;'
                  'font-size:var(--fs-meta);color:var(--muted)">'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/favicon.svg" alt="" width="18" height="18">favicon</span>'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/geekovski-icon.svg" alt="" width="18" height="18">знак</span>'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/geekovski-logo.svg" alt="" width="73" height="14" '
                  'style="background:#0A0C0F;padding:3px 6px;border-radius:var(--surface-corners,4px)">лого на тёмном</span>'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/geekovski-logo-light.svg" alt="" width="73" height="14" '
                  'style="background:#fff;padding:3px 6px;border-radius:var(--surface-corners,4px)">лого на светлом</span>'
                  '</div></section>') % icons

    # --- компоненты
    card = card_sample = ("<article class=\"sg-card\"><div class=\"card__body\"><div class=\"card__meta\">"
                          "<span class=\"chip cat-switch\">Nintendo Switch</span><time>3 ноября</time></div>"
                          "<h3 class=\"card__title\">Pikmin 4: демо уже в eShop</h3>"
                          "<p class=\"card__sum\">Стартовая зона и два экзамена Dandori Academy, сейв переносится.</p>"
                          "<div class=\"card__foot\"><a class=\"more\">Читать →</a><span>источников: 2</span></div>"
                          "</div></article>")
    item = ("<article class=\"ditem cat-switch\"><div class=\"ditem__rail\"><span class=\"ditem__num\">01</span>"
            "<span class=\"ditem__icon\">" + ICONS["switch"] + "</span></div><div class=\"ditem__body\">"
            "<div class=\"ditem__meta\"><span class=\"chip chip--sm cat-switch\">Nintendo Switch</span></div>"
            "<h3 class=\"ditem__title\">Демо Pikmin 4 уже в eShop</h3>"
            "<p class=\"ditem__text\">Стартовая зона и два экзамена Dandori Academy, сейв переносится.</p>"
            "<a class=\"ditem__src\">Nintendo Life</a></div></article>")
    row = ("<article class=\"drow is-evening\"><a class=\"drow__date\"><span class=\"drow__day\">3 ноября</span>"
           "<span class=\"drow__part\">ВЕЧЕР</span></a><div class=\"drow__body\">"
           "<h3 class=\"drow__title\">Убыток Anthropic, Crimson Desert на PS5</h3>"
           "<p class=\"drow__sum\">Квартальная выручка $17 млрд, Crimson Desert снова не держит 30 fps.</p>"
           "<div class=\"drow__tags\"><span class=\"chip chip--sm cat-ai\">AI</span></div></div>"
           "<span class=\"drow__count\">6 новостей</span></article>")
    share = share_block(SITE["url"] + "/style-guide.html", "Style Guide GEEKOVSKI", SITE["url"] + "/assets/img/og-default.png")
    comp_block = ('<section class="sg-block"><h2>Компоненты</h2>'
                  '<h3>Карточка материала</h3><div class="sg-demo">%s</div>'
                  '<h3>Новость в дайджесте</h3><div class="sg-demo sg-demo--narrow">%s</div>'
                  '<h3>Выпуск в списке дайджестов</h3><div class="sg-demo sg-demo--narrow">%s</div>'
                  '<h3>Поделиться</h3>%s</section>') % (card, item, row, share)

    content = ('<main class="wrap sg"><section class="lead"><h1>Style Guide</h1>'
               '<p>Единый набор типографики, цветов, компонентов и иконок блога. Всё, что не описано здесь, '
               'в вёрстке не используется.</p></section>%s%s%s%s%s</main>') % (
        type_block, palette_block, chip_block, icon_block, comp_block)

    return page("Style Guide — %s" % SITE["title"], "Типографика, цвета, компоненты и иконки GEEKOVSKI",
                content, theme, robots=ROBOTS_NOINDEX, metrika="", tmr="")


# ---------- дайджест: техническая мета и оформление ----------



def part_of_day(dt):
    return "Утро" if dt.hour < 12 else "Вечер"


def ru_date(dt):
    return "%d %s" % (dt.day, MONTHS_GEN[dt.month - 1])


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def news_count(n, word="новость"):
    """«36 статей» для выпуска-оглавления и «6 новостей» для обычного дайджеста."""
    if word == "статья":
        return "%d %s" % (n, plural(n, "статья", "статьи", "статей"))
    return "%d %s" % (n, plural(n, "новость", "новости", "новостей"))


def is_digest_of_articles(d):
    """Выпуск, где все записи ссылаются внутрь сайта, — это оглавление дня."""
    srcs = [(i.get("source") or "") for i in d["items"]]
    urls = [s.split("|")[-1].strip() for s in srcs if "|" in s]
    return bool(urls) and all(u.startswith(SITE["url"]) or u.startswith("/") for u in urls)


def strip_prefix(title):
    """«Вечер 3 ноября: Anthropic к IPO…» → «Anthropic к IPO…»"""
    return re.sub(r"^(Утро|Вечер|День)\s+\d{1,2}\s+[а-яё]+:\s*", "", title, flags=re.I).strip()


def sentence_case(text):
    """Заголовок с заглавной буквы. Числа и аббревиатуры не трогаем."""
    if not text:
        return text
    if text[0].isdigit() or (len(text) > 1 and text[1].isdigit()):
        return text
    return text[0].upper() + text[1:]


def digest_tags(d):
    seen, out = set(), []
    for it in d["items"]:
        c = CAT_ALIAS.get(it["category"], it["category"])
        if c in CAT_NAME and c not in seen:
            seen.add(c)
            out.append((c, CAT_NAME[c]))
    return out


def tags_html(d, solid=False):
    cls = "chip chip--solid" if solid else "chip chip--sm"
    return "".join('<span class="%s cat-%s">%s</span>' % (cls, c, n) for c, n in digest_tags(d))


# иконки рубрик — инлайн-SVG, без внешних библиотек
ICONS = {
    "xbox": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M7.5 7.5c2.6 2.4 4.2 5.1 6 9M16.5 7.5c-2.6 2.4-4.2 5.1-6 9"/></svg>',
    "switch": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="8" height="14" rx="3"/><rect x="13" y="5" width="8" height="14" rx="3"/><circle cx="7" cy="9" r="1.3"/><circle cx="17" cy="15" r="1.3"/></svg>',
    "playstation": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 8v9l4-1.5V6c1.2-.6 2 .2 2 1.8V14l5-2c2-.8 3 .2 3 1.8 0 1.4-.8 2.3-2.4 2.9L9 20"/></svg>',
    "pc": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="11" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
    "kino": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 6v12M16 6v12M3 12h18"/></svg>',
    "serialy": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="7" width="18" height="12" rx="2"/><path d="M8 3l4 4 4-4"/></svg>',
    "ai": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/></svg>',
    "vr": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 9h18v5a3 3 0 0 1-3 3h-3l-3-3-3 3H6a3 3 0 0 1-3-3z"/></svg>',
    "gadgets": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 5.5h3"/></svg>',
}


# ---------- дайджесты ----------

DIGEST_ITEM = """<article class="ditem cat-{cat}">
  <div class="ditem__rail"><span class="ditem__num">{num}</span><span class="ditem__icon">{icon}</span></div>
  <div class="ditem__body">
    <div class="ditem__meta"><span class="chip chip--sm cat-{cat}">{catname}</span></div>
    <h3 class="ditem__title">{title}</h3>
    <p class="ditem__text">{text}</p>
    {src}
  </div>
</article>"""


def digest_item(it, num):
    cat = CAT_ALIAS.get(it["category"], it["category"])
    if cat not in CAT_NAME:
        cat = "ai"
    src = ""
    if it.get("source"):
        name, _, url = it["source"].partition("|")
        name, url = name.strip(), url.strip()
        internal = url.startswith(SITE["url"]) or url.startswith("/")
        if internal and url:
            src = ('<a class="ditem__src ditem__src--in" href="%s">Читать статью →</a>'
                   % html.escape(url))
        else:
            src = ('<a class="ditem__src" href="%s" rel="nofollow noopener" target="_blank">%s</a>'
                   % (html.escape(url), html.escape(name or url))) if url else (
                   '<span class="ditem__src">%s</span>' % html.escape(name))
    return DIGEST_ITEM.format(cat=cat, catname=CAT_NAME.get(cat, cat), num="%02d" % num,
                              icon=ICONS.get(cat, ""), title=html.escape(it["title"]),
                              text=html.escape(it["summary"]), src=src)


def render_digest(d, theme, next_d=None, prev_d=None):
    from collections import OrderedDict
    groups = OrderedDict()
    for it in d["items"]:
        c = CAT_ALIAS.get(it["category"], it["category"])
        groups.setdefault(CAT_NAME.get(c, "Другое"), []).append(it)

    blocks = []
    # номер идёт подряд в порядке показа: раньше он брался из исходного списка,
    # и при группировке по рубрикам лента читалась как 01, 03, 32 — 02, 07
    n = 0
    for name, items in groups.items():
        rows = []
        for i in items:
            n += 1
            rows.append(digest_item(i, n))
        blocks.append('<section class="dgroup">%s</section>' % "".join(rows))

    head_title = strip_prefix(d["title"])
    word = "статья" if is_digest_of_articles(d) else "новость"
    meta = "%s · %s" % (ru_date(d["date"]), news_count(len(d["items"]), word))
    nav = ""
    if next_d or prev_d:
        nav = '<nav class="dnav">%s%s</nav>' % (
            '<a href="/digests/%s.html">← %s, %s</a>' % (prev_d["slug"], part_of_day(prev_d["date"]).lower(), ru_date(prev_d["date"])) if prev_d else "<span></span>",
            '<a href="/digests/%s.html">%s, %s →</a>' % (next_d["slug"], part_of_day(next_d["date"]).lower(), ru_date(next_d["date"])) if next_d else "<span></span>")

    content = """<main class="wrap digest-page">
{back}
<article class="digest is-{slot}">
  <header class="digest__head">
    <div class="digest__meta">
      <span class="digest__part"><span class="digest__dot"></span>{part}</span>
      <span class="digest__sep">·</span><span>{meta}</span>
    </div>
    <h1>{title}</h1>
    <div class="digest__tags">{tags}</div>
    {lead}
  </header>
  {blocks}
  {srcs}
  {share}
  {nav}
</article>
</main>""".format(
        part=part_of_day(d["date"]), slot=("morning" if d["date"].hour < 12 else "evening"),
        meta=html.escape(meta), title=html.escape(head_title),
        tags=tags_html(d), lead=('<p class="post__lead">%s</p>' % html.escape(d["summary"])) if d["summary"] else "",
        blocks="".join(blocks), nav=nav,
        share=share_block(SITE["url"] + "/digests/" + d["slug"] + ".html", d["title"]),
        back=back_link("Все дайджесты", "/digests/"),
        srcs=('<section class="sources"><h2>Все источники</h2><ol>%s</ol></section>' % "".join(
            '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>' % (
                html.escape(s["url"]), html.escape(s["name"])) for s in d["sources"] if s["url"])) if d["sources"] else "",
    )
    url = "%s/digests/%s.html" % (SITE["url"], d["slug"])
    # выпуск дайджеста — сводка ссылок, она не конкурирует со статьями в выдаче
    return page(title_tag(head_title), d["summary"] or meta, content, theme,
                canonical=url, og_type="article", article=d, og_alt=head_title,
                robots=ROBOTS_NOINDEX,
                og_image=SITE["url"] + d["cover"] if d["cover"] else None,
                jsonld=ldjson(ld_org(), ld_website(), ld_article(d, url, headline=head_title),
                              ld_breadcrumb([("Главная", "/"), ("Дайджесты", "/digests/"),
                                             (head_title, "/digests/%s.html" % d["slug"])])))


def render_digests_index(digests, theme):
    # Daily roundups can reuse a lead image from one of the articles they link to.
    article_covers = {publication_path(post): post["cover"] for post in ALL_POSTS
                      if post["kind"] == "post" and collection_cover(post["cover"])}
    cards = []
    for i, digest in enumerate(digests):
        date = digest["date"]
        meta = f'<time datetime="{iso(date)}">{release_date(date)} · {date:%H:%M}</time>'
        slot = "morning" if date.hour < 12 else "evening"
        meta += f' · {"Утро" if slot == "morning" else "Вечер"} · {news_count(len(digest["items"]))}'
        topics = "".join(f'<li>{html.escape(item["title"])}</li>' for item in digest["items"] if item["title"])
        credit = card_credit(digest["meta"].get("cover_source", ""))
        details = f'<details><summary>Темы выпуска</summary><ul>{topics}</ul>{credit}</details>' if topics else ""
        url = publication_path(digest)
        cover = digest["cover"]
        if not cover and is_digest_of_articles(digest):
            for item in digest["items"]:
                reference = item["source"].rpartition("|")[2].strip()
                cover = article_covers.get(urllib.parse.urlsplit(reference).path, "")
                if cover:
                    break
        cards.append(collection_card(digest["meta"].get("card_title") or sentence_case(strip_prefix(digest["title"])),
                                     url, digest["meta"].get("card_summary") or plain(digest["summary"], 160),
                                     meta, cover=cover, details=details, priority=i < 2,
                                     links=f'<a href="{html.escape(url)}">Читать выпуск ↗</a>',
                                     attrs=f' data-slot="{slot}" data-month="{date:%Y-%m}" data-date="{date:%Y-%m-%d}"'))
    controls = collection_filters("slot", [("", "Все выпуски"), ("morning", "Утро"), ("evening", "Вечер")],
                                   "Время выпуска")
    controls += month_filter(d["date"] for d in digests)
    content = collection_layout("Дайджесты", "Выпуски", controls, "".join(cards),
                                mode="digests", empty="За этот период выпусков нет.")
    url = SITE["url"] + "/digests/"
    desc = ("Дайджесты GEEKOVSKI: короткие выпуски новостей игр, техники, кино и AI с ссылками "
            "на первоисточники. Выпусков в архиве: %d." % len(digests))
    # лента дайджестов — навигация по архиву, а не контент для выдачи: noindex
    return page("Дайджесты — короткие новости GEEKOVSKI", desc, content, theme, canonical=url,
                robots=ROBOTS_NOINDEX,
                head_extra=collection_assets(),
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": "Дайджесты", "description": desc, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}},
                              ld_itemlist(digests, "Дайджесты") if digests else None,
                              ld_breadcrumb([("Главная", "/"), ("Дайджесты", "/digests/")])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="editorial", choices=["editorial", "dashboard", "magazine"])
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--content", default=None)
    ap.add_argument("--strict-images", action="store_true",
                    help="падать с кодом 1, если есть повторы или пропавшие картинки")
    a = ap.parse_args()
    ps = build(a.theme, a.out, a.content)
    print("theme=%s posts=%d -> %s" % (a.theme, len(ps), a.out))
    thin = [x for x in ps if not is_service(x) and len(re.findall(r"[^\W\d_]{2,}", x["body"])) < 600]
    if thin:
        print("тонкий контент: %d статей короче 600 слов (не блокер, но растёт медленнее)" % len(thin))
    vk_items = vk_selection(ps)
    print("vk.xml: %d анонсов (%s)" % (len(vk_items), ", ".join(p["slug"] for p in vk_items)))
    # WebP-копии рождаются во время рендера, то есть уже после первого копирования
    # static/img → out/assets/img. Досыпаем их в собранный сайт.
    webp_src = ROOT / "static" / "img"
    if webp_src.exists():
        for webp in webp_src.glob("*.webp"):
            dst = Path(a.out) / "assets" / "img" / webp.name
            if not dst.exists():
                shutil.copy(webp, dst)

    problems = image_report(ps)
    if problems:
        print("\nкартинки: проблем %d" % len(problems))
        for line in problems:
            print("  ·", line)
        if a.strict_images:
            raise SystemExit(1)
    else:
        print("картинки: повторов нет")

