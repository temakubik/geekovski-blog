#!/usr/bin/env python3
"""GEEKOVSKI static blog generator.

Читает content/posts/*.md, собирает статический сайт в docs/.
Только стандартная библиотека — ничего устанавливать не нужно.

  python3 build.py                 # собрать сайт из content/
  python3 build.py --theme magazine --out /tmp/preview
"""
import argparse
import html
import json
import os
import re
import shutil
import struct
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = {
    "title": "GEEKOVSKI",
    "tagline": "Технологии, игры и кино без маркетингового сиропа",
    "url": "https://geekovski.ru",
    "lang": "ru",
    "author": "GEEKOVSKI",
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
    if kind not in ("post", "digest", "calendar"):
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
        allowed = ("category", "title", "summary", "source", "platforms", "kind_note", "date", "where", "day", "cover")
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
    }


# ---------- markdown ----------

def md_inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    # ссылки: абсолютные И относительные (/rss.xml, /about.html) — на страницах сайта
    # используются оба вида, и раньше относительные оставались сырым markdown
    text = re.sub(r"\[([^\]]+)\]\(((?:https?://|/)[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return text


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

    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            flush()
            continue
        mi = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", s)
        if mi:
            flush()
            alt, src = mi.group(1), mi.group(2)
            out.append('<figure class="post__fig"><img src="%s" alt="%s" loading="lazy"></figure>' % (
                html.escape(src), html.escape(alt)))
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

NAV_COUNTS = {"posts": 0, "digests": 0, "rubrics": 0, "calendars": 0}
open_rubrics = {}   # заполняется в build(): слаг -> число материалов


def nav(**counts):
    """Шапка. Цифры в скобках — сколько статей, дайджестов и рубрик на сайте."""
    c = dict(NAV_COUNTS, **counts)
    c["rubrics"] = sum(1 for k, _ in CATS if open_rubrics.get(k))
    return ('<a class="nav__link nav__link--blog" href="/">Блог<span class="nav__num">(%d)</span></a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<a class="nav__link nav__link--digests" href="/digests/">Дайджесты<span class="nav__num">(%d)</span></a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<a class="nav__link nav__link--cal" href="/calendar/">Календарь<span class="nav__num">(%d)</span></a>'
            '<span class="nav__sep" aria-hidden="true"></span>'
            '<details class="nav__rubrics"><summary class="nav__link">Рубрики<span class="nav__num">(%d)</span></summary>'
            '<div class="nav__categories">'
            % (c["posts"], c["digests"], c["calendars"], c["rubrics"])
            + "".join('<a class="nav__link nav__link--sm" href="/{slug}/">{name}</a>'.format(slug=k, name=n)
                      for k, n in CATS) + '</div></details>')

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
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="/assets/img/favicon.svg">
<link rel="apple-touch-icon" href="/assets/img/apple-touch-icon.png">
<meta name="theme-color" content="#0A0C0F">
<link rel="alternate" type="application/rss+xml" title="GEEKOVSKI — лента" href="/rss.xml">
<link rel="alternate" type="application/feed+json" title="GEEKOVSKI — JSON-лента" href="/feed.json">
<link rel="sitemap" type="application/xml" href="/sitemap.xml">
<link rel="stylesheet" href="/assets/fonts.css">
<link rel="stylesheet" href="/assets/theme.css">
{metrika}
{jsonld}
</head>
<body class="t-{theme}">
<header class="top">
  <div class="wrap top__in">
    <a class="brand" href="/" aria-label="GEEKOVSKI — главная"><img class="brand__logo" src="/assets/img/geekovski-logo.svg" alt="GEEKOVSKI" width="1152" height="256" loading="eager"></a>
    <nav class="nav" id="site-nav" aria-label="Основное меню">{nav}</nav>
    <div class="top__actions">
      <button class="theme-toggle" title="Сменить тему" aria-label="Сменить тему">◐</button>
      <button class="menu-toggle" type="button" aria-controls="site-nav" aria-expanded="false" aria-label="Открыть меню"><span></span><span></span><span></span></button>
    </div>
  </div>
</header>
{content}
<footer class="foot">
  <div class="wrap foot__in">
    <span class="foot__brand"><img src="/assets/img/favicon.svg" alt="" width="18" height="18">© {year} GEEKOVSKI</span>
    <span class="foot__note">Мнение в текстах отделено от факта. Источники — в конце каждой заметки.</span>
    <span class="foot__links"><a href="/about.html">О сайте</a><a href="/rss.xml">RSS</a></span>
  </div>
</footer>
<script>
document.querySelector('.theme-toggle')?.addEventListener('click', () => {{
  const r = document.documentElement;
  r.dataset.mode = r.dataset.mode === 'light' ? 'dark' : 'light';
  localStorage.setItem('gv-mode', r.dataset.mode);
}});
if (localStorage.getItem('gv-mode')) document.documentElement.dataset.mode = localStorage.getItem('gv-mode');
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
document.addEventListener('keydown', (event) => {{ if (event.key === 'Escape') {{ closeMenu(); if (rubrics) rubrics.open = false; }} }});
const route = location.pathname;
const active = route === '/' ? '.nav__link--blog' : route.startsWith('/digests/') ? '.nav__link--digests' : '.nav__rubrics > summary';
document.querySelector(active)?.classList.add('nav__link--active');
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
</body>
</html>
"""


DEFAULT_OG = SITE["url"] + "/assets/img/og-default.png"

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
        head = path.read_bytes()[:262144]
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
    """crumbs — [(название, путь от корня)], первым идёт («Главная», «/»)."""
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE["url"] + path}
            for i, (name, path) in enumerate(crumbs)
        ],
    }


def ld_itemlist(posts, name):
    return {
        "@type": "ItemList", "name": name, "numberOfItems": len(posts),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "url": SITE["url"] + "/" + p["slug"] + ".html", "name": p["title"]}
            for i, p in enumerate(posts)
        ],
    }


def ld_article(p, url, image_url=None):
    """BlogPosting для материалов, Article для дайджестов.

    citation со ссылками на первоисточники — сигнал проверяемости: на такие страницы
    охотнее ссылаются ответы AI-поиска.
    """
    body_text = p["body"] if p["kind"] == "post" else " ".join(i["summary"] for i in p["items"])
    obj = {
        "@type": "Article" if p["kind"] == "digest" else "BlogPosting",
        "@id": url + "#article",
        "headline": p["title"],
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


def page(title, desc, content, theme, og_image=None, canonical=None, jsonld="",
         og_type="website", robots=ROBOTS_INDEX, article=None, og_alt=None,
         metrika=None):
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
    return PAGE.format(
        theme=theme, title=html.escape(title), desc=html.escape(desc),
        nav=nav(), content=content, year=datetime.now().year,
        og_image_meta=og_image_meta(og_image, og_alt or title),
        og_url=og_url, canonical=canonical_tag, robots=robots, og_type=og_type,
        article_meta=article_meta, jsonld=jsonld,
        metrika=METRIKA_COUNTER if metrika is None else metrika,
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


def card(p, theme, big=False):
    cat = p["category"]
    # обложка получает alt из заголовка: пустой alt оставляем только декоративным плашкам
    cover = ('<div class="card__cover"><img src="%s" alt="%s" loading="lazy"></div>'
             % (p["cover"], html.escape(p["title"], quote=True))) if p["cover"] else ""
    # чип рубрики — ссылка: даёт краулеру путь из каждой карточки в раздел
    return """<article class="card card--{cls} cat-{cat}">
  {cover}
  <div class="card__body">
    <div class="card__meta"><a class="chip cat-{cat}" href="/{cat}/">{catname}</a><time datetime="{isodt}">{date}</time></div>
    <h3 class="card__title"><a href="/{slug}.html">{title}</a></h3>
    <p class="card__sum">{sum}</p>
    <div class="card__foot"><a class="more" href="/{slug}.html">Читать →</a>{src}</div>
  </div>
</article>""".format(
        cls="big" if big else "", cat=cat, catname=CAT_NAME.get(cat, cat),
        date=p["date"].strftime("%d.%m"), isodt=iso(p["date"]),
        slug=p["slug"], title=html.escape(p["title"]),
        sum=html.escape(first_sentence(p["summary"] or plain(p["body"], 130), limit=125 if not big else 170)), cover=cover,
        src=('<span class="srcc">источников: %d</span>' % len(p["sources"])) if p["sources"] else "",
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


def render_index(posts, theme, digests=None, cal_entries=None):
    if not posts:
        return page(HOME_TITLE, HOME_DESC, '<main class="wrap"><p>Пусто.</p></main>', theme,
                    canonical=SITE["url"] + "/", jsonld=ldjson(ld_org(), ld_website()))
    if theme == "magazine":
        head = hero(posts[0])
        cards = "\n".join(card(p, theme, big=(i < 2)) for i, p in enumerate(posts[1:]))
        content = '<main class="wrap"><div class="hero-wrap">%s</div><div class="grid grid--mag">%s</div></main>' % (head, cards)
    elif theme == "dashboard":
        cards = "\n".join(card(p, theme) for p in posts)
        content = ('<main class="wrap"><section class="lead"><h1>Последнее</h1><p>%s</p></section>'
                   '<div class="grid grid--cards">%s</div></main>') % (SITE["tagline"], cards)
    if theme == "editorial":
        dg = locals().get("digests") or []
        dblock = ""
        if dg:
            latest = dg[0]
            dblock = ('<section class="rubric rubric--digest"><div class="rubric__head"><h2>Дайджесты</h2>'
                      '<a class="rubric__all" href="/digests/">Все дайджесты →</a></div>'
                      '<a class="dteaser" href="/digests/%s.html"><span class="dteaser__date">%s</span>'
                      '<strong>%s</strong><span class="dteaser__count">%d новостей</span></a></section>') % (
                latest["slug"], latest["date"].strftime("%d.%m, %H:%M"), html.escape(latest["title"]), len(latest["items"]))
        # Одна лента: сверху два закреплённых больших материала, дальше сетка по четыре,
        # всё сортировано по дате — без группировки по рубрикам, которая оставляла дырки.
        lead2 = posts[:2]
        rest = posts[2:]
        top = ('<section class="lead-two">%s</section>'
               % "\n".join(card(p, theme, big=True) for p in lead2)) if lead2 else ""
        feed_rows = "\n".join(card(p, theme) for p in rest)
        feed = ('<section class="feed-block"><div class="rubric__head"><h2>Все материалы</h2>'
                '<span class="rubric__all">%d %s</span></div>'
                '<div class="grid grid--feed">%s</div></section>'
                % (len(posts), plural(len(posts), "материал", "материала", "материалов"), feed_rows)) if rest else ""
        cstrip = calendar_strip(cal_entries or [], theme)
        content = '<main class="wrap">%s%s%s%s</main>' % (dblock, cstrip, top, feed)
    else:  # magazine
        head = hero(posts[0])
        cards = "\n".join(card(p, theme) for p in posts[1:])
        content = '<main class="wrap"><div class="hero-wrap">%s</div><div class="grid grid--mag">%s</div></main>' % (head, cards)
    return page(HOME_TITLE, HOME_DESC, content, theme,
                canonical=SITE["url"] + "/",
                og_alt="GEEKOVSKI — игры, технологии и кино",
                jsonld=ldjson(ld_org(), ld_website(),
                              ld_itemlist(posts[:12], "Свежие материалы GEEKOVSKI")))


def share_block(url, title, image=None):
    """Кнопки «поделиться». Ссылки — обычные share-URL соцсетей, без сторонних скриптов."""
    u = urllib.parse.quote(url, safe="")
    tx = urllib.parse.quote(title, safe="")
    img = urllib.parse.quote(image or DEFAULT_OG, safe="")
    return ("""<section class="share" data-share-root>
  <span class="share__label">Поделиться</span>
  <a class="share__btn" href="https://t.me/share/url?url={u}&text={t}" target="_blank" rel="noopener nofollow">Telegram</a>
  <a class="share__btn" href="https://vk.com/share.php?url={u}&title={t}" target="_blank" rel="noopener nofollow">ВКонтакте</a>
  <a class="share__btn" href="https://wa.me/?text={t}%20{u}" target="_blank" rel="noopener nofollow">WhatsApp</a>
  <a class="share__btn" href="https://x.com/intent/tweet?url={u}&text={t}" target="_blank" rel="noopener nofollow">X</a>
  <a class="share__btn" href="https://ru.pinterest.com/pin/create/button/?url={u}&media={i}&description={t}" target="_blank" rel="noopener nofollow">Pinterest</a>
  <button class="share__btn share__btn--copy" type="button" data-copy="{u}">Скопировать ссылку</button>
</section>""").format(u=u, t=tx, i=img)


def render_post(p, posts, theme):
    related = [x for x in posts if x["category"] == p["category"] and x["slug"] != p["slug"]][:3]
    srcs = ""
    if p["sources"]:
        srcs = '<section class="sources"><h2>Источники</h2><ol>%s</ol></section>' % "".join(
            '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>' % (html.escape(s["url"]), html.escape(s["name"]))
            if s["url"] else "<li>%s</li>" % html.escape(s["name"]) for s in p["sources"])
    body = md(p["body"])
    # «Коротко»: список фактов из frontmatter tldr — то, что можно процитировать
    # в ответе, не пересказывая статью.
    tldr = ""
    if p.get("tldr"):
        tldr = ('<aside class="tldr"><h2 class="tldr__title">Коротко</h2><ul>%s</ul></aside>'
                % "".join("<li>%s</li>" % md_inline(x) for x in p["tldr"]))
    cover = ""
    if p["cover"]:
        cover = ('<figure class="post__cover"><img src="%s" alt="%s"></figure>'
                 % (p["cover"], html.escape(p["title"], quote=True)))
    # CC BY / CC BY-SA требуют указания автора и лицензии: держим их мелкой строкой в конце,
    # а не подписью под картинкой. CC0 и public domain — без упоминания.
    credit_line = ""
    if p.get("credit") and "CC BY" in p["credit"]:
        credit_line = ('<p class="imgcredit">Изображения: %s</p>'
                       % html.escape(p["credit"].replace("Обложка: ", "")))
    rel = ""
    if related:
        rel = '<section class="related"><h2>По теме</h2><div class="grid grid--list">%s</div></section>' % "\n".join(
            card(x, theme) for x in related)
    content = """<main class="wrap">
<article class="post cat-{cat}">
  <header class="post__head">
    <div class="post__meta"><a class="chip chip--solid cat-{cat}" href="/{cat}/">{catname}</a><time datetime="{isodt}">{date}</time></div>
    <h1>{title}</h1>
    <p class="post__lead">{sum}</p>
  </header>
  {tldr}
  {cover}
  <div class="post__body">{body}</div>
  {credit_line}
  {srcs}
  {share}
</article>
{rel}
</main>""".format(
        cat=p["category"], catname=CAT_NAME.get(p["category"], p["category"]),
        date=p["date"].strftime("%d.%m.%Y, %H:%M"), isodt=iso(p["date"]),
        title=html.escape(p["title"]),
        sum=html.escape(p["summary"]), cover=cover, body=body, srcs=srcs, rel=rel,
        tldr=tldr,
        credit_line=credit_line,
        share=share_block(SITE["url"] + "/" + p["slug"] + ".html", p["title"],
                          SITE["url"] + (p["pin"] or p["cover"]) if (p["pin"] or p["cover"]) else None),
    )
    og = SITE["url"] + p["cover"] if p["cover"] else None
    url = SITE["url"] + "/" + p["slug"] + ".html"
    catname = CAT_NAME.get(p["category"], p["category"])
    return page(title_tag(p["title"]),
                p["summary"] or plain(p["body"], 160),
                content, theme, og_image=og, canonical=url, og_type="article",
                article=p, og_alt=p["title"],
                jsonld=ldjson(ld_org(), ld_website(), ld_article(p, url),
                              ld_breadcrumb([("Главная", "/"), (catname, "/%s/" % p["category"]),
                                             (p["title"], "/%s.html" % p["slug"])])))


def title_tag(text, brand=SITE["title"], limit=68):
    """Заголовок для <title>: бренд добавляем только если влезаем в сниппет.

    Длинный H1 (а он у нас любит быть длинным) с « — GEEKOVSKI» превращается в 90+
    символов, и поиск обрезает самое важное — начало. Бренд в этом случае лишний:
    домен и так подписан в выдаче.
    """
    if len(text) + 3 + len(brand) <= limit:
        return "%s — %s" % (text, brand)
    return text


def render_cat(slug, name, items, theme):
    cards = "\n".join(card(p, theme) for p in items)
    count = "%d %s" % (len(items), plural(len(items), "материал", "материала", "материалов"))
    if items:
        body = '<div class="grid grid--%s">%s</div>' % ("cards" if theme == "dashboard" else "list", cards)
        desc = ("%s: %s — разборы новостей с источниками и датами. %s"
                % (name, count, SITE["tagline"]))
    else:
        # пустая рубрика не должна выглядеть сломанной: говорим прямо и уводим в дайджесты
        body = ('<p class="lead__empty">Здесь пока пусто — рубрика только открылась. '
                'Свежие новости по всем направлениям выходят в <a href="/digests/">дайджестах</a>, '
                'а разборы появляются на главной.</p>')
        desc = "%s: рубрика открыта — материалы с разбором новостей и ссылками на источники. %s" % (name, SITE["tagline"])
    content = ('<main class="wrap"><section class="lead"><h1>%s</h1><p>%s</p></section>%s</main>'
               % (html.escape(name), count if items else "рубрика открыта", body))
    url = SITE["url"] + "/%s/" % slug
    return page("%s — новости и разборы | %s" % (name, SITE["title"]), desc, content, theme,
                canonical=url, og_alt="%s — GEEKOVSKI" % name,
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": name, "description": desc, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}},
                              ld_itemlist(items, name) or None,
                              ld_breadcrumb([("Главная", "/"), (name, "/%s/" % slug)])))


def rss(posts, title=None, path=""):
    items = "".join("""<item><title>{t}</title><link>{u}/{p}{s}.html</link>
<guid>{u}/{p}{s}.html</guid><pubDate>{d}</pubDate><description>{desc}</description></item>""".format(
        t=html.escape(p["title"]), u=SITE["url"], p=path, s=p["slug"], d=p["date"].strftime("%a, %d %b %Y %H:%M:%S +0300"),
        desc=html.escape(p["summary"])) for p in posts[:40])
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{title}</title><link>{url}</link>
<description>{tag}</description><language>ru</language>{items}</channel></rss>""".format(
        title=title or SITE["title"], url=SITE["url"], tag=SITE["tagline"], items=items)


def sitemap(posts, digests=None):
    """Sitemap с lastmod у каждой записи и картинками материалов.

    lastmod без него поисковики перекачивают всё подряд; image:image пускает обложки
    в поиск по картинкам (в Яндексе это отдельная выдача).
    """
    def entry(loc, lastmod=None, image=None, caption=None):
        parts = ["<loc>%s</loc>" % loc]
        if lastmod:
            parts.append("<lastmod>%s</lastmod>" % lastmod)
        if image:
            parts.append('<image:image><image:loc>%s</image:loc>%s</image:image>'
                         % (image, "<image:title>%s</image:title>" % html.escape(caption) if caption else ""))
        return "<url>%s</url>" % "".join(parts)

    newest = max([p["date"] for p in posts] or [datetime.now()])
    urls = [entry(SITE["url"] + "/", newest.strftime("%Y-%m-%d"))]
    for c, _ in CATS:
        items = [p for p in posts if p["category"] == c]
        urls.append(entry(SITE["url"] + "/%s/" % c,
                          max([p["date"] for p in items]).strftime("%Y-%m-%d") if items else None))
    urls.append(entry(SITE["url"] + "/digests/"))
    urls.append(entry(SITE["url"] + "/about.html"))
    for d in (digests or []):
        urls.append(entry("%s/digests/%s.html" % (SITE["url"], d["slug"]), d["date"].strftime("%Y-%m-%d")))
    for p in posts:
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
    lines = ["# GEEKOVSKI — robots.txt", "User-agent: *", "Allow: /",
             "Disallow: /style-guide.html", ""]
    lines += ["User-agent: %s" % b for b in bots]
    lines += ["Allow: /", "Disallow: /style-guide.html", "", "Sitemap: %s/sitemap.xml" % SITE["url"],
              "Host: %s" % SITE["url"].split("//")[1], ""]
    return "\n".join(lines)


def llms_txt(posts, digests):
    """llms.txt по llmstxt.org: короткая карта сайта для языковых моделей.

    Не заменяет индексацию, но даёт LLM готовый список материалов со ссылками,
    датами и сутью — то, из чего собирается ответ со ссылкой на источник.
    """
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
    out += ["- [Дайджесты](%s/digests/): короткие выпуски новостей" % SITE["url"], "", "## Материалы", ""]
    for p in posts:
        out.append("- [%s](%s/%s.html): %s (%s)" % (
            p["title"], SITE["url"], p["slug"], (p["summary"] or plain(p["body"], 160)).replace("\n", " "),
            p["date"].strftime("%d.%m.%Y")))
    if digests:
        out += ["", "## Дайджесты", ""]
        for d in digests:
            out.append("- [%s](%s/digests/%s.html): %s" % (
                d["title"], SITE["url"], d["slug"], (d["summary"] or "").replace("\n", " ")))
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


def build(theme, out_dir, content_dir=None):
    content = Path(content_dir) if content_dir else ROOT / "content"
    everything = [parse_post(p) for p in sorted((content / "posts").glob("*.md"))]
    everything = [p for p in everything if not p["draft"]]
    everything.sort(key=lambda p: p["date"], reverse=True)
    posts = [p for p in everything if p["kind"] == "post"]
    digests = [p for p in everything if p["kind"] == "digest"]
    calendars = [p for p in everything if p["kind"] == "calendar"]
    cal_entries = calendar_entries(calendars)

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
    (out / "assets" / "theme.css").write_text("\n".join(parts), encoding="utf-8")
    for extra in (ROOT / "static" / "assets").glob("*") if (ROOT / "static" / "assets").exists() else []:
        shutil.copy(extra, out / "assets" / extra.name)
    fonts_src = ROOT / "static" / "fonts"
    if fonts_src.exists():
        (out / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
        for pattern in ("*.woff2", "*.ttf"):
            for f in fonts_src.glob(pattern):
                shutil.copy(f, out / "assets" / "fonts" / f.name)
        shutil.copy(ROOT / "static" / "fonts.css", out / "assets" / "fonts.css")
    img_src = ROOT / "static" / "img"
    if img_src.exists():
        (out / "assets" / "img").mkdir(parents=True, exist_ok=True)
        for img in img_src.glob("*"):
            if img.is_file():
                shutil.copy(img, out / "assets" / "img" / img.name)

    open_rubrics.clear()
    for c, _n in CATS:
        open_rubrics[c] = len([p for p in posts if p["category"] == c])
    NAV_COUNTS["posts"] = len(posts)
    NAV_COUNTS["digests"] = len(digests)
    NAV_COUNTS["calendars"] = sum(1 for e in cal_entries if e["day"] >= datetime.now().date())
    (out / "index.html").write_text(render_index(posts, theme, digests, cal_entries), encoding="utf-8")
    for p in posts:
        (out / ("%s.html" % p["slug"])).write_text(render_post(p, posts, theme), encoding="utf-8")
    for c, name in CATS:
        d = out / c
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(render_cat(c, name, [p for p in posts if p["category"] == c], theme), encoding="utf-8")
    (out / "rss.xml").write_text(rss(posts), encoding="utf-8")
    dgdir = out / "digests"
    dgdir.mkdir(exist_ok=True)
    (dgdir / "index.html").write_text(render_digests_index(digests, theme), encoding="utf-8")
    for i, d in enumerate(digests):
        nxt = digests[i - 1] if i > 0 else None      # новее
        prv = digests[i + 1] if i + 1 < len(digests) else None
        (dgdir / ("%s.html" % d["slug"])).write_text(render_digest(d, theme, nxt, prv), encoding="utf-8")
    cdir = out / "calendar"
    cdir.mkdir(exist_ok=True)
    (cdir / "index.html").write_text(render_calendar_page(cal_entries, theme), encoding="utf-8")
    (out / "style-guide.html").write_text(render_style_guide(theme), encoding="utf-8")
    (out / "404.html").write_text(render_404(theme), encoding="utf-8")
    about = render_about(theme)
    if about:
        (out / "about.html").write_text(about, encoding="utf-8")
    (out / "robots.txt").write_text(robots_txt(), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(posts, digests), encoding="utf-8")
    (out / "llms-full.txt").write_text(llms_full_txt(posts), encoding="utf-8")
    (out / "feed.xml").write_text(rss(digests, title="%s — дайджесты" % SITE["title"], path="digests"), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(posts, digests), encoding="utf-8")
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

WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]


PLATFORMS = {
    "switch2": ("Switch 2", "switch"), "switch": ("Switch", "switch"),
    "ps5": ("PS5", "playstation"), "ps4": ("PS4", "playstation"),
    "xbox": ("Xbox Series", "xbox"), "pc": ("PC", "pc"), "mac": ("Mac", "pc"),
    "vr": ("VR", "vr"), "netflix": ("Netflix", "serialy"), "kino": ("Кино", "kino"),
    "tv": ("ТВ", "serialy"),
}


def _cal_icon(kind_note):
    """Иконка по типу анонса: релиз / порт / сериал."""
    k = (kind_note or "").lower()
    if "сериал" in k or "фильм" in k:
        return ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
                'stroke-width="1.7"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M8 3l4 4 4-4"/></svg>')
    if "порт" in k or "ремастер" in k or "ремейк" in k:
        return ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
                'stroke-width="1.7"><path d="M4 12a8 8 0 0 1 13.7-5.6M20 12a8 8 0 0 1-13.7 5.6"/><path d="M18 4v4h-4M6 20v-4h4"/></svg>')
    return ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
            'stroke-width="1.7"><path d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="4"/></svg>')


def _cal_week(entries, today=None):
    """Ближайшие 7 дней: от сегодня до +6."""
    today = today or datetime.now().date()
    return [e for e in entries if 0 <= (e["day"] - today).days <= 6]


def _plat_tags(value):
    """'pc ps5 switch2' → chips. Незнакомое значение печатаем как текст."""
    out = []
    for tok in (value or "").split():
        label, cat = PLATFORMS.get(tok.lower(), (tok, None))
        cls = "plat plat--%s" % cat if cat else "plat"
        out.append('<span class="%s">%s</span>' % (cls, html.escape(label)))
    return "".join(out)


def _cal_card(e):
    """Карточка анонса: картинка 16:9, тип, название, платформы."""
    visual = ""
    if e.get("cover"):
        visual = '<div class="anno__cover"><img src="%s" alt="%s" loading="lazy"></div>' % (
            e["cover"], html.escape(e["title"], quote=True))
    else:
        visual = '<div class="anno__cover anno__cover--mono"><span>%s</span></div>' % html.escape(
            e["title"][:2].upper())
    return ('<article class="anno cat-{cat}">{visual}'
            '<div class="anno__body"><div class="anno__meta"><span class="anno__type">{icon}{note}</span>'
            '<span class="anno__cat">{catname}</span></div>'
            '<h3 class="anno__title">{title}</h3>'
            '<div class="anno__plat">{plats}</div></div></article>').format(
        cat=e["category"], visual=visual, icon=_cal_icon(e["kind_note"]),
        catname=CAT_NAME.get(e["category"], e["category"]),
        note=html.escape(e["kind_note"] or "релиз"), title=html.escape(e["title"]),
        plats=_plat_tags(e["platforms"]))


def render_calendar_page(entries, theme, today=None):
    today = today or datetime.now().date()
    week = _cal_week(entries, today)
    # дальше — «Дальше по календарю», сгруппировано по месяцам
    later = [e for e in entries if (e["day"] - today).days > 6]
    groups = {}
    for e in week:
        groups.setdefault(e["day"], []).append(e)

    blocks = []
    for day in sorted(groups):
        d = datetime.combine(day, datetime.min.time())
        rel = "сегодня" if day == today else ("завтра" if (day - today).days == 1 else "")
        head = ('<div class="cal__day"><span class="cal__how"><span class="cal__num">%02d</span>'
                '<span class="cal__month">%s</span></span><span class="cal__wd">%s</span>%s</div>') % (
            d.day, MONTHS_GEN[d.month - 1], WD[d.weekday()],
            ('<span class="cal__rel">%s</span>' % rel) if rel else "")
        cards = "".join(_cal_card(e) for e in groups[day])
        blocks.append('<section class="cal__group">%s<div class="cal__cards">%s</div></section>' % (head, cards))

    if not blocks:
        body = ('<p class="lead__empty">На ближайшую неделю подтверждённых дат пока нет. '
                'Как только анонсы появятся — они окажутся здесь.</p>')
        desc = "Что выходит на этой неделе: игры, фильмы и сериалы с подтверждёнными датами. " + SITE["tagline"]
    else:
        body = '<div class="cal">%s</div>' % "".join(blocks)
        desc = ("Календарь анонсов: %d %s на этой неделе с подтверждёнными датами — "
                "игры, платформы, фильмы и сериалы. %s") % (
            len(week), plural(len(week), "релиз", "релиза", "релизов"), SITE["tagline"])

    # месяцы дальше недели: старые месяцы остаются в истории, новые добавляются блоком
    if later:
        months = {}
        for e in later:
            months.setdefault((e["day"].year, e["day"].month), []).append(e)
        mblocks = []
        for (y, m) in sorted(months):
            rows = "".join(
                '<a class="mrow cat-%s" href="%s"><span class="mrow__d">%02d</span>'
                '<span class="mrow__t">%s</span><span class="mrow__p">%s</span></a>'
                % (e["category"], e["href"], e["day"].day, html.escape(e["title"]), _plat_tags(e["platforms"]))
                for e in months[(y, m)])
            mblocks.append('<section class="mblock"><h3 class="mblock__h">%s %d</h3>%s</section>'
                           % (MONTHS_NOM[m - 1], y, rows))
        body += ('<section class="cal-later"><div class="rubric__head"><h2>Дальше по календарю</h2>'
                 '<span class="rubric__all">%d %s</span></div>%s</section>'
                 % (len(later), plural(len(later), "дата", "даты", "дат"), "".join(mblocks)))

    content = ('<main class="wrap"><section class="lead"><h1>Календарь анонсов</h1>'
               '<p>Что выходит на этой неделе и что уже назначено дальше. Только подтверждённые даты.</p></section>'
               '%s</main>') % body
    return page("Календарь анонсов — что выходит на этой неделе | %s" % SITE["title"], desc, content, theme,
                canonical=SITE["url"] + "/calendar/",
                jsonld=ldjson(ld_org(), ld_website()))


def calendar_entries(calendars):
    """Разворачивает заметки kind: calendar в плоский список записей."""
    out = []
    for c in calendars:
        for it in c["items"]:
            day = None
            try:
                day = datetime.strptime(it.get("date", ""), "%Y-%m-%d").date()
            except ValueError:
                continue
            out.append({
                "day": day, "category": it["category"], "title": it["title"],
                "cover": it.get("cover", ""),
                "platforms": it.get("platforms", ""), "kind_note": it.get("kind_note", ""),
                "summary": it["summary"], "source": it["source"],
                "href": (it["source"].split("|")[-1].strip() if "|" in it["source"] else "/calendar/"),
            })
    out.sort(key=lambda e: (e["day"], e["title"]))
    return out


def calendar_strip(entries, theme, limit=3, today=None):
    """Плашка «ближайшая неделя» на главной."""
    week = _cal_week(entries, today)[:limit]
    if not week:
        return ""
    rows = "".join(
        '<a class="cstrip__row cat-{cat}" href="{href}"><span class="cstrip__d">{d}</span>'
        '<span class="cstrip__t">{t}</span><span class="cstrip__p">{p}</span></a>'.format(
            cat=e["category"], href=e["href"],
            d="%02d.%02d" % (e["day"].day, e["day"].month),
            t=html.escape(e["title"]), p=html.escape(e["platforms"]))
        for e in week)
    return ('<section class="cstrip"><div class="rubric__head"><h2>Календарь анонсов</h2>'
            '<a class="rubric__all" href="/calendar/">Вся неделя →</a></div>%s</section>') % rows


# ---------- Style Guide ----------

def _swatch(name, var, note=""):
    return ('<div class="sg-swatch"><span class="sg-swatch__chip" style="background:%s"></span>'
            '<span class="sg-swatch__name">%s</span><span class="sg-swatch__hex">%s</span>'
            '<span class="sg-swatch__note">%s</span></div>' % (var, name, var, note))


def render_style_guide(theme):
    months = ["ВЕЧЕР", "УТРО"]
    rows = []

    # --- типографика
    type_rows = [
        ("H0 · заголовок статьи", "h0", "var(--fs-h0) · 52 px · дисплейный, 900 italic", "Убыток Anthropic и Crimson Desert на PS5"),
        ("H1 · герой, H2 в тексте", "h1", "var(--fs-h1) · 40 px", "Ocarina of Time выходит 5 ноября"),
        ("H2 · карточки, H3 в тексте", "h2", "var(--fs-h2) · 24 px", "Pikmin 4: демо уже в eShop"),
        ("Лид", "lead-text", "var(--fs-lead) · 17 px · Medeo Sans", "Демо Pikmin 4 в eShop, Zelda выходит 5 ноября, Circana зафиксировала падение продаж."),
        ("Основной текст", "body-text", "var(--fs-body) · 16 px · Medeo Sans", "Nintendo провела Pikmin Direct, предупредив за десять минут до эфира."),
        ("Мелкий текст", "small-text", "var(--fs-small) · 14 px", "Стартовая зона и два экзамена Dandori Academy"),
        ("Метка · капитель", "meta-text", "var(--fs-meta) · 12 px · Chava", "NINTENDO SWITCH · 3 НОЯБРЯ"),
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
        ("accent", "#C9F24D", "акцент"),
    ]
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
                  '<p class="sg-hint">Chava, 12 px, uppercase, разрядка .08em. Цвет — маркер рубрики, не акцент.</p></section>') % chips

    # --- иконки рубрик
    icons = "".join('<div class="sg-icon"><span class="ditem__icon cat-%s">%s</span><span>%s</span></div>'
                    % (c, ICONS.get(c, ""), name) for c, name in CATS)
    icon_block = ('<section class="sg-block"><h2>Иконки рубрик</h2><div class="sg-icons">%s</div>'
                  '<p class="sg-hint">Инлайн-SVG 24×24, цвет наследуется от рубрики. Иконки бренда: '
                  '<img src="/assets/img/favicon.svg" alt="" width="18" height="18" style="vertical-align:middle"> favicon · '
                  '<img src="/assets/img/logo.svg" alt="" width="18" height="18" style="vertical-align:middle"> лого.</p></section>') % icons

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
                content, theme, robots=ROBOTS_NOINDEX, metrika="")


# ---------- дайджест: техническая мета и оформление ----------

MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]


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


def news_count(n):
    return "%d %s" % (n, plural(n, "новость", "новости", "новостей"))


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

    # нумерация сквозная по всему выпуску
    numbered, n = {}, 0
    for it in d["items"]:
        n += 1
        numbered[id(it)] = n
    blocks = []
    for name, items in groups.items():
        rows = "".join(digest_item(i, numbered[id(i)]) for i in items)
        blocks.append('<section class="dgroup">%s</section>' % rows)

    head_title = strip_prefix(d["title"])
    meta = "%s · %s" % (ru_date(d["date"]), news_count(len(d["items"])))
    nav = ""
    if next_d or prev_d:
        nav = '<nav class="dnav">%s%s</nav>' % (
            '<a href="/digests/%s.html">← %s, %s</a>' % (prev_d["slug"], part_of_day(prev_d["date"]).lower(), ru_date(prev_d["date"])) if prev_d else "<span></span>",
            '<a href="/digests/%s.html">%s, %s →</a>' % (next_d["slug"], part_of_day(next_d["date"]).lower(), ru_date(next_d["date"])) if next_d else "<span></span>")

    content = """<main class="wrap">
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
        srcs=('<section class="sources"><h2>Все источники</h2><ol>%s</ol></section>' % "".join(
            '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>' % (
                html.escape(s["url"]), html.escape(s["name"])) for s in d["sources"] if s["url"])) if d["sources"] else "",
    )
    url = "%s/digests/%s.html" % (SITE["url"], d["slug"])
    return page(title_tag(head_title), d["summary"] or meta, content, theme,
                canonical=url, og_type="article", article=d, og_alt=head_title,
                jsonld=ldjson(ld_org(), ld_website(), ld_article(d, url),
                              ld_breadcrumb([("Главная", "/"), ("Дайджесты", "/digests/"),
                                             (head_title, "/digests/%s.html" % d["slug"])])))


def render_digests_index(digests, theme):
    rows = []
    for d in digests:
        rows.append("""<article class="drow cat-{cat} is-{slot}">
  <a class="drow__date" href="/digests/{slug}.html"><span class="drow__day">{day}</span><span class="drow__part">{part}</span></a>
  <div class="drow__body">
    <h3 class="drow__title"><a href="/digests/{slug}.html">{title}</a></h3>
    <p class="drow__sum">{sum}</p>
    <div class="drow__tags">{tags}</div>
  </div>
  <span class="drow__count">{count}</span>
</article>""".format(slot=("morning" if d["date"].hour < 12 else "evening"),
                    cat=(digest_tags(d)[0][0] if digest_tags(d) else "ai"),
                    slug=d["slug"], part=part_of_day(d["date"]).upper(), day=ru_date(d["date"]),
                    title=html.escape(sentence_case(strip_prefix(d["title"]))), sum=html.escape(d["summary"]),
                    tags=tags_html(d), count=news_count(len(d["items"]))))
    content = ('<main class="wrap"><section class="lead"><h1>Дайджесты</h1>'
               '<p>Коротко о том, что произошло — утром в 9 и вечером в 19. Из самого интересного потом выходят большие статьи в блоге.</p>'
               '</section><div class="dlist">%s</div></main>') % ("".join(rows) or "<p>Пока пусто.</p>")
    url = SITE["url"] + "/digests/"
    desc = ("Дайджесты GEEKOVSKI: короткие выпуски новостей игр, техники, кино и AI с ссылками "
            "на первоисточники. Выпусков в архиве: %d." % len(digests))
    return page("Дайджесты — короткие новости GEEKOVSKI", desc, content, theme,
                canonical=url, og_alt="Дайджесты GEEKOVSKI",
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
    a = ap.parse_args()
    ps = build(a.theme, a.out, a.content)
    print("theme=%s posts=%d -> %s" % (a.theme, len(ps), a.out))

