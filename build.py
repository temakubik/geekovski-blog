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
    return {
        "slug": slug,
        "title": meta.get("title", "Без заголовка"),
        "date": date,
        "category": cat,
        "summary": meta.get("summary", ""),
        "cover": meta.get("cover", ""),
        "body": body.strip(),
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

NAV = "".join(
    '<a class="nav__link" href="/{slug}/">{name}</a>'.format(slug=c, name=n) for c, n in CATS
)

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
<link rel="alternate" type="application/rss+xml" href="/rss.xml">
<link rel="stylesheet" href="/assets/theme.css">
</head>
<body class="t-{theme}">
<header class="top">
  <div class="wrap top__in">
    <a class="brand" href="/"><span class="brand__mark">G</span><span class="brand__name">GEEKOVSKI</span></a>
    <nav class="nav">{nav}</nav>
    <button class="theme-toggle" title="Сменить тему" aria-label="Сменить тему">◐</button>
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
    cover = ('<div class="card__cover" style="--h:%d">%s</div>' % (
        abs(hash(p["slug"])) % 40 + 20,
        '<img src="%s" alt="" loading="lazy">' % p["cover"] if p["cover"] else "",
    ))
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
    return """<section class="hero">
  <a class="hero__link" href="/{slug}.html">
    <span class="chip chip--solid">{catname}</span>
    <h1>{title}</h1>
    <p>{sum}</p>
    <span class="hero__cta">Читать разбор →</span>
  </a>
</section>""".format(
        slug=p["slug"], catname=CAT_NAME.get(p["category"], p["category"]),
        title=html.escape(p["title"]), sum=html.escape(p["summary"] or plain(p["body"], 220)),
    )


def render_index(posts, theme):
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
        head = hero(posts[0])
        blocks = []
        for c, name in CATS:
            items = [p for p in posts if p["category"] == c][:4]
            if not items:
                continue
            rows = "\n".join(card(p, theme) for p in items)
            blocks.append(
                '<section class="rubric"><div class="rubric__head"><h2>%s</h2>'
                '<a class="rubric__all" href="/%s/">Все материалы →</a></div>'
                '<div class="grid grid--list">%s</div></section>' % (name, c, rows))
        content = '<main class="wrap"><div class="hero-wrap">%s</div>%s</main>' % (head, "\n".join(blocks))
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
    cover = '<figure class="post__cover"><img src="%s" alt=""></figure>' % p["cover"] if p["cover"] else ""
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


def rss(posts):
    items = "".join("""<item><title>{t}</title><link>{u}/{s}.html</link>
<guid>{u}/{s}.html</guid><pubDate>{d}</pubDate><description>{desc}</description></item>""".format(
        t=html.escape(p["title"]), u=SITE["url"], s=p["slug"], d=p["date"].strftime("%a, %d %b %Y %H:%M:%S +0300"),
        desc=html.escape(p["summary"])) for p in posts[:40])
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{title}</title><link>{url}</link>
<description>{tag}</description><language>ru</language>{items}</channel></rss>""".format(
        title=SITE["title"], url=SITE["url"], tag=SITE["tagline"], items=items)


def sitemap(posts):
    urls = ["<url><loc>%s/</loc></url>" % SITE["url"]]
    urls += ['<url><loc>%s/%s/</loc></url>' % (SITE["url"], c) for c, _ in CATS]
    urls += ["<url><loc>{u}/{s}.html</loc><lastmod>{d}</lastmod></url>".format(
        u=SITE["url"], s=p["slug"], d=p["date"].strftime("%Y-%m-%d")) for p in posts]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(urls)


def build(theme, out_dir, content_dir=None):
    content = Path(content_dir) if content_dir else ROOT / "content"
    posts = [parse_post(p) for p in sorted((content / "posts").glob("*.md"))]
    posts = [p for p in posts if not p["draft"]]
    posts.sort(key=lambda p: p["date"], reverse=True)

    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    shutil.copy(ROOT / "static" / "themes" / ("%s.css" % theme), out / "assets" / "theme.css")
    for extra in (ROOT / "static" / "assets").glob("*") if (ROOT / "static" / "assets").exists() else []:
        shutil.copy(extra, out / "assets" / extra.name)

    (out / "index.html").write_text(render_index(posts, theme), encoding="utf-8")
    for p in posts:
        (out / ("%s.html" % p["slug"])).write_text(render_post(p, posts, theme), encoding="utf-8")
    for c, name in CATS:
        d = out / c
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(render_cat(c, name, [p for p in posts if p["category"] == c], theme), encoding="utf-8")
    (out / "rss.xml").write_text(rss(posts), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(posts), encoding="utf-8")
    (out / "feed.json").write_text(json.dumps([
        {k: (v.strftime("%Y-%m-%dT%H:%M:%S") if isinstance(v, datetime) else v)
         for k, v in p.items() if k in ("slug", "title", "date", "category", "summary", "sources")}
        for p in posts], ensure_ascii=False, indent=1), encoding="utf-8")
    if (ROOT / "static" / "CNAME").exists():
        shutil.copy(ROOT / "static" / "CNAME", out / "CNAME")
    return posts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="editorial", choices=["editorial", "dashboard", "magazine"])
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--content", default=None)
    a = ap.parse_args()
    ps = build(a.theme, a.out, a.content)
    print("theme=%s posts=%d -> %s" % (a.theme, len(ps), a.out))
