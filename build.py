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
    ("kino", "Кино"),
    ("serialy", "Сериалы"),
    ("ai", "AI"),
]
CAT_NAME = dict(CATS)
# старые слаги заметок → новые рубрики
CAT_ALIAS = {"gadgets": "pc", "igry": "switch", "techno": "ai"}


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
    if kind not in ("post", "digest"):
        kind = "post"
    items, cur = [], None
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        # «- category: switch» открывает новость, «title: …» / «summary: …» её дополняют
        m = re.match(r"^(?:-\s+)?([a-z_]+):\s*(.*)$", s)
        if not (m and m.group(1) in ("category", "title", "summary", "source")):
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "category":
            cur = {"category": val.lower(), "title": "", "summary": "", "source": ""}
            items.append(cur)
        elif cur is not None:
            cur[key] = val
    if kind != "digest":
        items, body_lines = [], body.splitlines()
    else:
        body_lines = []
    return {
        "items": items,
        "kind": kind,
        "slug": slug,
        "title": meta.get("title", "Без заголовка"),
        "date": date,
        "category": cat,
        "summary": meta.get("summary", ""),
        "cover": meta.get("cover", ""),
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
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
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
            cap = "<figcaption>%s</figcaption>" % html.escape(alt) if alt else ""
            out.append('<figure class="post__fig"><img src="%s" alt="%s" loading="lazy">%s</figure>' % (
                html.escape(src), html.escape(alt), cap))
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

NAV = ('<a class="nav__link nav__link--blog" href="/">Блог</a>'
       '<span class="nav__sep" aria-hidden="true"></span>'
       '<a class="nav__link nav__link--digests" href="/digests/">Дайджесты</a>'
       '<span class="nav__sep" aria-hidden="true"></span>'
       '<details class="nav__rubrics"><summary class="nav__link">Рубрики</summary>'
       '<div class="nav__categories">'
       + "".join('<a class="nav__link nav__link--sm" href="/{slug}/">{name}</a>'.format(slug=c, name=n)
                 for c, n in CATS) + '</div></details>')

PAGE = """<!DOCTYPE html>
<html lang="ru" data-theme="{theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<link rel="icon" type="image/svg+xml" href="/assets/img/geekovski-icon.svg">
<link rel="apple-touch-icon" href="/assets/img/apple-touch-icon.png">
<meta name="theme-color" content="#0A0C0F">
<link rel="alternate" type="application/rss+xml" href="/rss.xml">
<link rel="stylesheet" href="/assets/fonts.css">
<link rel="stylesheet" href="/assets/theme.css">
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
    <span>© {year} GEEKOVSKI</span>
    <span class="foot__note">Мнение в текстах отделено от факта. Источники — в конце каждой заметки.</span>
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
</body>
</html>
"""


def page(title, desc, content, theme):
    return PAGE.format(
        theme=theme, title=html.escape(title), desc=html.escape(desc),
        nav=NAV, content=content, year=datetime.now().year,
    )


def card(p, theme, big=False):
    cat = p["category"]
    cover = ('<div class="card__cover"><img src="%s" alt="" loading="lazy"></div>' % p["cover"]) if p["cover"] else ""
    return """<article class="card card--{cls} cat-{cat}">
  {cover}
  <div class="card__body">
    <div class="card__meta"><span class="chip">{catname}</span><time>{date}</time></div>
    <h3 class="card__title"><a href="/{slug}.html">{title}</a></h3>
    <p class="card__sum">{sum}</p>
    <div class="card__foot"><a class="more" href="/{slug}.html">Читать →</a>{src}</div>
  </div>
</article>""".format(
        cls="big" if big else "", cat=cat, catname=CAT_NAME.get(cat, cat),
        date=p["date"].strftime("%d.%m"), slug=p["slug"], title=html.escape(p["title"]),
        sum=html.escape(p["summary"] or plain(p["body"], 150)), cover=cover,
        src=('<span class="srcc">источников: %d</span>' % len(p["sources"])) if p["sources"] else "",
    )


def hero(p):
    img = '<div class="hero__cover"><img src="%s" alt="" loading="lazy"></div>' % p["cover"] if p["cover"] else ""
    return """<section class="hero">
  <a class="hero__link" href="/{slug}.html">
    """ + img + """
    <span class="chip chip--solid">{catname}</span>
    <h1>{title}</h1>
    <p>{sum}</p>
    <span class="hero__cta">Читать разбор →</span>
  </a>
</section>""".format(
        slug=p["slug"], catname=CAT_NAME.get(p["category"], p["category"]),
        title=html.escape(p["title"]), sum=html.escape(p["summary"] or plain(p["body"], 220)),
    )


def render_index(posts, theme, digests=None):
    if not posts:
        return page(SITE["title"], SITE["tagline"], '<main class="wrap"><p>Пусто.</p></main>', theme)
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
        head = hero(posts[0])
        blocks = []
        for c, name in CATS:
            items = [p for p in posts if p["category"] == c and p["slug"] != posts[0]["slug"]][:4]
            if not items:
                continue
            rows = "\n".join(card(p, theme) for p in items)
            blocks.append(
                '<section class="rubric"><div class="rubric__head"><h2>%s</h2>'
                '<a class="rubric__all" href="/%s/">Все материалы →</a></div>'
                '<div class="grid grid--list">%s</div></section>' % (name, c, rows))
        content = '<main class="wrap">%s<div class="hero-wrap">%s</div>%s</main>' % (dblock, head, "\n".join(blocks))
    else:  # magazine
        head = hero(posts[0])
        cards = "\n".join(card(p, theme) for p in posts[1:])
        content = '<main class="wrap"><div class="hero-wrap">%s</div><div class="grid grid--mag">%s</div></main>' % (head, cards)
    return page(SITE["title"], SITE["tagline"], content, theme)


def render_post(p, posts, theme):
    related = [x for x in posts if x["category"] == p["category"] and x["slug"] != p["slug"]][:3]
    srcs = ""
    if p["sources"]:
        srcs = '<section class="sources"><h2>Источники</h2><ol>%s</ol></section>' % "".join(
            '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>' % (html.escape(s["url"]), html.escape(s["name"]))
            if s["url"] else "<li>%s</li>" % html.escape(s["name"]) for s in p["sources"])
    body = md(p["body"])
    cover = ""
    if p["cover"]:
        cap = '<figcaption>%s</figcaption>' % html.escape(p["credit"]) if p.get("credit") else ""
        cover = '<figure class="post__cover"><img src="%s" alt="">%s</figure>' % (p["cover"], cap)
    rel = ""
    if related:
        rel = '<section class="related"><h2>По теме</h2><div class="grid grid--list">%s</div></section>' % "\n".join(
            card(x, theme) for x in related)
    content = """<main class="wrap">
<article class="post cat-{cat}">
  <header class="post__head">
    <div class="post__meta"><span class="chip chip--solid">{catname}</span><time>{date}</time></div>
    <h1>{title}</h1>
    <p class="post__lead">{sum}</p>
  </header>
  {cover}
  <div class="post__body">{body}</div>
  {srcs}
</article>
{rel}
</main>""".format(
        cat=p["category"], catname=CAT_NAME.get(p["category"], p["category"]),
        date=p["date"].strftime("%d.%m.%Y, %H:%M"), title=html.escape(p["title"]),
        sum=html.escape(p["summary"]), cover=cover, body=body, srcs=srcs, rel=rel,
    )
    return page("%s — %s" % (p["title"], SITE["title"]), p["summary"] or plain(p["body"], 160), content, theme)


def render_cat(slug, name, items, theme):
    cards = "\n".join(card(p, theme) for p in items)
    content = ('<main class="wrap"><section class="lead"><h1>%s</h1><p>%d материалов</p></section>'
               '<div class="grid grid--%s">%s</div></main>') % (
        html.escape(name), len(items), "cards" if theme == "dashboard" else "list", cards)
    return page("%s — %s" % (name, SITE["title"]), name, content, theme)


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
    urls = ["<url><loc>%s/</loc></url>" % SITE["url"]]
    urls += ['<url><loc>%s/%s/</loc></url>' % (SITE["url"], c) for c, _ in CATS]
    urls.append("<url><loc>%s/digests/</loc></url>" % SITE["url"])
    for d in (digests or []):
        urls.append("<url><loc>{u}/digests/{s}.html</loc><lastmod>{d}</lastmod></url>".format(
            u=SITE["url"], s=d["slug"], d=d["date"].strftime("%Y-%m-%d")))
    urls += ["<url><loc>{u}/{s}.html</loc><lastmod>{d}</lastmod></url>".format(
        u=SITE["url"], s=p["slug"], d=p["date"].strftime("%Y-%m-%d")) for p in posts]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(urls)


def build(theme, out_dir, content_dir=None):
    content = Path(content_dir) if content_dir else ROOT / "content"
    everything = [parse_post(p) for p in sorted((content / "posts").glob("*.md"))]
    everything = [p for p in everything if not p["draft"]]
    everything.sort(key=lambda p: p["date"], reverse=True)
    posts = [p for p in everything if p["kind"] == "post"]
    digests = [p for p in everything if p["kind"] == "digest"]

    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    shutil.copy(ROOT / "static" / "themes" / ("%s.css" % theme), out / "assets" / "theme.css")
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

    (out / "index.html").write_text(render_index(posts, theme, digests), encoding="utf-8")
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
    (out / "feed.xml").write_text(rss(digests, title="%s — дайджесты" % SITE["title"], path="digests"), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(posts, digests), encoding="utf-8")
    (out / "feed.json").write_text(json.dumps([
        {k: (v.strftime("%Y-%m-%dT%H:%M:%S") if isinstance(v, datetime) else v)
         for k, v in p.items() if k in ("slug", "title", "date", "category", "summary", "sources")}
        for p in posts], ensure_ascii=False, indent=1), encoding="utf-8")
    ico = ROOT / "static" / "img" / "favicon.ico"
    if ico.exists():
        shutil.copy(ico, out / "favicon.ico")
    (out / ".nojekyll").write_text("")
    if (ROOT / "static" / "CNAME").exists():
        shutil.copy(ROOT / "static" / "CNAME", out / "CNAME")
    return posts

# ---------- дайджесты ----------

DIGEST_ITEM = """<article class="ditem">
  <div class="ditem__meta"><span class="chip chip--sm cat-{cat}">{catname}</span></div>
  <h3 class="ditem__title">{title}</h3>
  <p class="ditem__text">{text}</p>
  {src}
</article>"""


def digest_item(it):
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
    return DIGEST_ITEM.format(cat=cat, catname=CAT_NAME.get(cat, cat), title=html.escape(it["title"]),
                              text=html.escape(it["summary"]), src=src)


def render_digest(d, theme, next_d=None, prev_d=None):
    from collections import OrderedDict
    groups = OrderedDict()
    for it in d["items"]:
        c = CAT_ALIAS.get(it["category"], it["category"])
        groups.setdefault(CAT_NAME.get(c, "Другое"), []).append(it)
    blocks = []
    for name, items in groups.items():
        blocks.append('<section class="dgroup"><h2>%s</h2>%s</section>' % (
            html.escape(name), "".join(digest_item(i) for i in items)))
    nav = ""
    if next_d or prev_d:
        nav = '<nav class="dnav">%s%s</nav>' % (
            '<a href="/digests/%s.html">← %s</a>' % (prev_d["slug"], prev_d["date"].strftime("%d.%m, %H:%M")) if prev_d else "<span></span>",
            '<a href="/digests/%s.html">%s →</a>' % (next_d["slug"], next_d["date"].strftime("%d.%m, %H:%M")) if next_d else "<span></span>")
    content = """<main class="wrap">
<article class="digest">
  <header class="post__head">
    <div class="post__meta"><span class="chip chip--solid">Дайджест</span><time>{date}</time></div>
    <h1>{title}</h1>
    <p class="post__lead">{sum} · {count} новостей</p>
  </header>
  {body}
  {blocks}
  {srcs}
  {nav}
</article>
</main>""".format(
        date=d["date"].strftime("%d.%m.%Y, %H:%M"), title=html.escape(d["title"]),
        sum=html.escape(d["summary"]), count=len(d["items"]), blocks="".join(blocks),
        body=md(d["body"]) if d["body"] else "", nav=nav,
        srcs=('<section class="sources"><h2>Все источники</h2><ol>%s</ol></section>' % "".join(
            '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>' % (
                html.escape(s["url"]), html.escape(s["name"])) for s in d["sources"] if s["url"])) if d["sources"] else "",
    )
    return page("%s — %s" % (d["title"], SITE["title"]), d["summary"], content, theme)


def render_digests_index(digests, theme):
    rows = []
    for d in digests:
        rows.append("""<article class="drow">
  <div class="drow__meta"><time>{date}</time><span class="drow__count">{count} новостей</span></div>
  <h3 class="drow__title"><a href="/digests/{slug}.html">{title}</a></h3>
  <p class="drow__sum">{sum}</p>
</article>""".format(date=d["date"].strftime("%d.%m.%Y, %H:%M"), count=len(d["items"]),
                    slug=d["slug"], title=html.escape(d["title"]), sum=html.escape(d["summary"])))
    content = ('<main class="wrap"><section class="lead"><h1>Дайджесты</h1>'
               '<p>Коротко о том, что произошло — утром в 9 и вечером в 19. Из самого интересного потом выходят большие статьи в блоге.</p>'
               '</section><div class="dlist">%s</div></main>') % ("".join(rows) or "<p>Пока пусто.</p>")
    return page("Дайджесты — %s" % SITE["title"], "Дважды в день: короткие новости", content, theme)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="editorial", choices=["editorial", "dashboard", "magazine"])
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--content", default=None)
    a = ap.parse_args()
    ps = build(a.theme, a.out, a.content)
    print("theme=%s posts=%d -> %s" % (a.theme, len(ps), a.out))

