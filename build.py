#!/usr/bin/env python3
"""GEEKOVSKI static blog generator.

Читает content/posts/*.md, собирает статический сайт в docs/.
Только стандартная библиотека — ничего устанавливать не нужно.

  python3 build.py                 # собрать сайт из content/
  python3 build.py --theme magazine --out /tmp/preview
"""
import argparse
import collections
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
    if kind not in ("post", "digest", "calendar", "game", "film", "series"):
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
            '<a class="nav__link nav__link--authors" href="/avtory/">Авторы</a>'
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
<meta name="theme-color" content="#0A0C0F">
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
<link rel="stylesheet" href="/assets/theme.css">
<link rel="stylesheet" href="/assets/brand.css">
<script>try{{const m=localStorage.getItem('gv-mode');if(m)document.documentElement.dataset.mode=m}}catch(e){{}}</script>
{metrika}
{ga}
{tmr}
{jsonld}
{digest_css}
</head>
<body class="t-{theme}">
<header class="top">
  <div class="wrap top__in">
    <a class="brand" href="/" aria-label="GEEKOVSKI — главная"><img class="brand__logo brand__logo--dark" src="/assets/img/geekovski-logo.svg" alt="GEEKOVSKI" width="418" height="80" loading="eager"><img class="brand__logo brand__logo--light" src="/assets/img/geekovski-logo-light.svg" alt="" width="418" height="80" loading="eager" aria-hidden="true"></a>
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
    <span class="foot__links"><a href="/avtory/">Авторы</a><a href="/about.html">О сайте</a><a href="/rss.xml">RSS</a><a class="foot__ext" href="{vk}" target="_blank" rel="noopener">ВКонтакте</a></span>
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
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {{}}));
}}
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
    return PAGE.format(
        theme=theme, title=html.escape(title), desc=html.escape(desc),
        nav=nav(), content=content, year=datetime.now().year, vk=SITE["vk"],
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


def card(p, theme, big=False, h1=False, summary=True):
    cat = p["category"]
    head_tag = "h1" if h1 else "h3"
    # обложка получает alt из заголовка: пустой alt оставляем только декоративным плашкам
    cover = ('<div class="card__cover"><img src="%s" alt="%s" loading="lazy"></div>'
             % (p["cover"], html.escape(p["title"], quote=True))) if p["cover"] else ""
    # чип рубрики — ссылка: даёт краулеру путь из каждой карточки в раздел
    return """<article class="card card--{cls} cat-{cat}">
  {cover}
  <div class="card__body">
    <div class="card__meta"><a class="chip cat-{cat}" href="/{cat}/">{catname}</a><time datetime="{isodt}">{date}</time></div>
    <{head_tag} class="card__title"><a href="/{slug}.html">{title}</a></{head_tag}>
    {sum_block}
    <div class="card__foot"><a class="more" href="/{slug}.html">Читать →</a>{src}</div>
  </div>
</article>""".format(
        cls="big" if big else "", cat=cat, catname=CAT_NAME.get(cat, cat), head_tag=head_tag,
        date=p["date"].strftime("%d.%m"), isodt=iso(p["date"]),
        slug=p["slug"], title=html.escape(p["title"]),
        sum_block=('<p class="card__sum">%s</p>'
                   % html.escape(first_sentence(p["summary"] or plain(p["body"], 130),
                                                limit=125 if not big else 170))) if summary else "",
        cover=cover,
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
                latest["slug"], latest["date"].strftime("%d.%m, %H:%M"), html.escape(strip_prefix(latest["title"])), len(latest["items"]))
        # Одна лента: сверху два закреплённых больших материала, дальше сетка по четыре,
        # всё сортировано по дате — без группировки по рубрикам, которая оставляла дырки.
        lead2 = posts[:2]
        rest = posts[2:]
        top = ('<section class="lead-two">%s</section>'
               % "\n".join(card(p, theme, big=True, h1=(i == 0), summary=False)
                            for i, p in enumerate(lead2))) if lead2 else ""
        # автор просил на главной только заголовки: описания остаются на страницах
        # рубрик и в поиске, а в ленте от них рябило и карточки разъезжались по высоте
        feed_rows = "\n".join(card(p, theme, summary=False) for p in rest)
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



# ---------- перелинковка: тайтл ↔ статьи ----------

def _aliases(t):
    """Как тайтл может упоминаться в тексте: заголовок, короткое имя и slug-варианты."""
    names = [t["title"]]
    raw = t.get("aliases") or ""
    if raw:
        names += [x.strip() for x in raw.split("|") if x.strip()]
    return [n for n in names if len(n) >= 3]


def link_articles_to_titles(html_text):
    """Первое упоминание тайтла в тексте статьи → ссылка на его страницу.
    Работает по чистому тексту ДО markdown, поэтому длинные имена
    обрабатываются первыми и ссылки не вкладываются друг в друга."""
    if not TITLES:
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
    alias_map = {}
    for slug, t in TITLES.items():
        for name in _aliases(t):
            alias_map.setdefault(name.lower(), (name, slug))
    if not alias_map:
        return html_text
    names = sorted(alias_map, key=len, reverse=True)
    pat = re.compile(r"(?<![\w\[/])(" + "|".join(re.escape(n) for n in names) + r")(?![\w\]])",
                     re.IGNORECASE)
    done = set()

    def _rep(m):
        name, slug = alias_map[m.group(1).lower()]
        if slug in done:
            return m.group(1)
        done.add(slug)
        return "[%s](/titles/%s.html)" % (m.group(1), slug)

    linked = pat.sub(_rep, html_text)
    if stash:
        linked = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], linked)
    return linked


def articles_for_title(slug):
    """Все материалы и новости дайджестов, где упомянут тайтл."""
    t = TITLES.get(slug)
    if not t:
        return []
    names = [re.escape(n) for n in _aliases(t)]
    pat = re.compile("|".join(names), re.IGNORECASE) if names else None
    if not pat:
        return []
    hits = []
    for post in ALL_POSTS:
        parts = [post["title"], post["summary"], post["body"] or ""]
        if post["kind"] == "digest":
            parts += [i["title"] + " " + i["summary"] for i in post["items"]]
        if pat.search(" ".join(parts)):
            # текст, где тайтл упомянут именно в новости, а не только в метаданных
            hits.append(post)
    return hits[:12]


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


def render_post(p, posts, theme):
    related = [x for x in posts if x["category"] == p["category"] and x["slug"] != p["slug"]][:3]
    p = dict(p, body=link_articles_to_titles(p["body"]))
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
    content = """<main class="wrap post-page">
{back}
<article class="post cat-{cat}">
  <header class="post__head">
    <div class="post__meta"><a class="chip chip--solid cat-{cat}" href="/{cat}/">{catname}</a><time datetime="{isodt}">{date}</time></div>
    <h1>{title}</h1>
    <p class="post__lead">{sum}</p>
    {byline}
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
        sum=html.escape(p["summary"]), cover=cover,
        body=body, srcs=srcs, rel=rel,
        tldr=tldr, byline=byline,
        credit_line=credit_line,
        back=back_link("Назад", "/%s/" % p["category"]),
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
    content = ('<main class="wrap">%s<section class="lead"><h1>%s</h1><p>%s</p></section>%s</main>'
               % (back_link("На главную", "/"), html.escape(name),
                  count if items else "рубрика открыта", body))
    url = SITE["url"] + "/%s/" % slug
    return page("%s — новости и разборы | %s" % (name, SITE["title"]), desc, content, theme,
                canonical=url, og_alt="%s — GEEKOVSKI" % name,
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": url + "#page", "url": url,
                               "name": name, "description": desc, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}},
                              ld_itemlist(items, name) or None,
                              ld_breadcrumb([("Главная", "/"), (name, "/%s/" % slug)])))


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


def sitemap(posts, digests=None, titles=None, with_calendar=False, authors=None):
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
    for slug in sorted(titles or {}):
        urls.append(entry(SITE["url"] + "/titles/" + slug + ".html"))
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


# У страницы /digests/ лид (.lead) идёт вплотную к переключателю, и его нижняя
# граница читалась как непонятная линия без заголовка. Убираем рамку только тут.
DIGEST_HIDE_LEAD = ".lead { border-bottom: 0; padding-bottom: 10px; margin-bottom: 14px; }"

# Стили переключателя видов дайджестов и сетки календаря лежат здесь, а не в
# editorial.css. Причина: в большом theme.css (50 КБ) Chromium переставал
# применять правила, стоящие после тяжёлого блока (баг разбора: файл читался
# целиком, а последние ~36 правил отбрасывались). Отдаём их отдельным
# inline-<style> и проверяем страницу в браузере, а не только в CSS-файле.
DIGEST_VIEW_CSS = """/* Дайджесты: вида два — список и две недели календарём. */
.dviews { margin: 0 0 22px; }
.dviews__tabs {
  display: inline-flex; gap: 4px; padding: 4px; margin: 0 0 20px;
  border: 1px solid var(--line); border-radius: 12px; background: var(--panel);
}
.dviews__tab {
  font-family: var(--font-caps); font-size: var(--fs-meta); letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); background: transparent;
  border: 0; border-radius: 8px; padding: 9px 20px; cursor: pointer;
  transition: color .15s, background .15s;
}
.dviews__tab:hover { color: var(--text); }
/* активный таб — тёмный с лаймовой рамкой: чёрный текст на синем не читался */
.dviews__tab.is-on { color: var(--accent); background: rgba(55, 123, 240, .16); box-shadow: inset 0 0 0 1px var(--accent); }

.stripx { display: grid; grid-template-columns: auto 1fr auto; gap: 14px; align-items: center; margin-bottom: 14px; }
.stripx__range { font-family: var(--font-caps); font-size: var(--fs-small); letter-spacing: .12em; text-transform: uppercase; color: var(--text); }
.stripx__wd { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }
.stripx__w { text-align: center; font-family: var(--font-caps); font-size: var(--fs-meta); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.stripx__row { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }
.stripx__cell {
  position: relative; aspect-ratio: 4 / 3; border-radius: 10px;
  border: 1px solid var(--line); background: var(--bg); color: var(--muted);
  display: grid; grid-template-rows: auto 1fr; align-items: start;
  padding: 7px 9px 8px; cursor: default; transition: border-color .15s, background .15s;
}
.stripx__cell.has { color: var(--text); cursor: pointer; }
.stripx__cell.has:hover { border-color: var(--accent); background: var(--panel); }
.stripx__cell.today { box-shadow: inset 0 0 0 1px rgba(55, 123, 240, .55); }
.stripx__cell.active { border-color: var(--accent); background: rgba(55, 123, 240, .16); }
.stripx__n { font-family: var(--font-display); font-style: italic; font-size: var(--fs-card); line-height: 1; }
/* «эта неделя» и «следующая»: вторая строка приглушена, первая — на панели */
.stripx__cell.next { background: transparent; opacity: .72; }
.stripx__cell.has .stripx__n { color: var(--text); }
.stripx__cell.active .stripx__n { color: var(--accent); }
.stripx__dots { align-self: end; display: flex; gap: 4px; }
.stripx__dot { width: 7px; height: 7px; border-radius: 50%; background: #F5C518; }

.stripx__dot.is-evening { background: var(--part-eve, #A855F7); }
.stripx__nav {
  width: 42px; height: 42px; border-radius: 10px; border: 1px solid var(--line);
  background: var(--panel); color: var(--text); cursor: pointer; font-size: 17px; line-height: 1;
  transition: border-color .15s, color .15s, transform .1s;
}
.stripx__nav:hover { border-color: var(--accent); color: var(--accent); }
.stripx__nav:active { transform: scale(.95); }
.stripx__panel { border-top: 1px solid var(--line); padding-top: 14px; margin-top: 4px; }
.stripx__ptitle { font-family: var(--font-caps); font-size: var(--fs-meta); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
.stripx__item { display: grid; grid-template-columns: max-content 1fr auto; gap: 12px; align-items: baseline; padding: 11px 0; border-bottom: 1px solid var(--line); text-decoration: none; }
.stripx__item:last-child { border-bottom: 0; }
.stripx__item:hover .stripx__name { color: var(--accent); }
.stripx__part { font-family: var(--font-caps); font-size: var(--fs-meta); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.stripx__name { font-family: var(--font-display); font-style: italic; font-size: var(--fs-card); line-height: 1.25; }
.stripx__count { font-family: var(--font-mono); font-size: var(--fs-meta); color: var(--muted); }

@media (max-width: 640px) {
  .dviews__tabs { display: flex; width: 100%; }
  .dviews__tab { flex: 1 1 0; padding: 9px 10px; letter-spacing: .06em; }
  .stripx { grid-template-columns: 1fr auto; gap: 10px; }
  .stripx__wd { display: none; }
  .stripx__range { grid-column: 1; }
  .stripx__nav { grid-row: 1; }
  .stripx__row { gap: 4px; }
  .stripx__cell { padding: 6px; border-radius: 8px; }
  .stripx__n { font-size: var(--fs-small); }
}
"""


def build(theme, out_dir, content_dir=None):
    content = Path(content_dir) if content_dir else ROOT / "content"
    everything = [parse_post(p) for p in sorted((content / "posts").glob("*.md"))]
    everything = [p for p in everything if not p["draft"]]
    everything.sort(key=lambda p: p["date"], reverse=True)
    posts = [p for p in everything if p["kind"] == "post"]
    digests = [p for p in everything if p["kind"] == "digest"]
    calendars = [p for p in everything if p["kind"] == "calendar"]
    cal_entries = calendar_entries(calendars)
    CAL_ENTRIES[:] = cal_entries
    TITLES.clear()
    TITLES.update(load_titles())
    AUTHORS[:] = load_authors(content)
    AUTHOR_BY_CAT.clear()
    for a in AUTHORS:
        for c in a["categories"]:
            AUTHOR_BY_CAT.setdefault(c, a)
    ALL_POSTS[:] = posts + digests

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
    NAV_COUNTS["calendars"] = sum(1 for e in cal_entries if e["day"] >= datetime.now().date())
    (out / "index.html").write_text(render_index(posts, theme, digests, cal_entries), encoding="utf-8")
    for p in posts:
        (out / ("%s.html" % p["slug"])).write_text(render_post(p, posts, theme), encoding="utf-8")
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
    tdir = out / "titles"
    tdir.mkdir(exist_ok=True)
    for slug in TITLES:
        htmlp = title_page(slug, theme)
        if htmlp:
            (tdir / ("%s.html" % slug)).write_text(htmlp, encoding="utf-8")
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
            '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
            '<title>Календарь анонсов — GEEKOVSKI</title>'
            '<meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="%s/calendar/">'
            '<meta http-equiv="refresh" content="0; url=/calendar/">'
            '</head><body><p>Календарь переехал: <a href="/calendar/">geekovski.ru/calendar/</a></p>'
            '<script>location.replace("/calendar/")</script></body></html>' % SITE["url"],
            encoding="utf-8")
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
        "background_color": "#0A0C0F",
        "theme_color": "#0A0C0F",
        "icons": [
            {"src": "/assets/img/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/assets/img/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "/assets/img/favicon-192.png", "sizes": "192x192", "type": "image/png"},
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy(ROOT / "static" / "sw.js", out / "sw.js")
    (out / "offline.html").write_text(offline_page(theme), encoding="utf-8")
    (out / "robots.txt").write_text(robots_txt(), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(posts, digests, TITLES, AUTHORS), encoding="utf-8")
    (out / "llms-full.txt").write_text(llms_full_txt(posts), encoding="utf-8")
    (out / "feed.xml").write_text(rss(digests, title="%s — дайджесты" % SITE["title"], path="digests",
                                     self_name="feed.xml"), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(posts, digests, TITLES, with_calendar=bool(cal_entries),
                                            authors=AUTHORS),
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

WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN_MONTH = ["января", "февраля", "марта", "апреля", "мая", "июня",
                   "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]


PLATFORMS = {
    "switch2": ("Switch 2", "switch"), "switch": ("Switch", "switch"),
    "ps5": ("PS5", "playstation"), "ps4": ("PS4", "playstation"),
    "xbox": ("Xbox Series", "xbox"), "pc": ("PC", "pc"), "mac": ("Mac", "pc"),
    "vr": ("VR", "vr"), "netflix": ("Netflix", "serialy"), "prime": ("Prime Video", "serialy"), "kino": ("Кино", "kino"),
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


def _same_as_category(e):
    """Тип анонса, совпадающий с названием рубрики, второй раз не печатаем."""
    note = (e["kind_note"] or "").strip().lower()
    cat = CAT_NAME.get(e["category"], "").lower()
    if not note:
        return False
    return note in cat or cat in note


def _cal_card(e):
    """Карточка анонса: картинка 16:9, тип, название, платформы."""
    visual = ""
    if e.get("cover"):
        visual = '<div class="anno__cover"><img src="%s" alt="%s" loading="lazy"></div>' % (
            e["cover"], html.escape(e["title"], quote=True))
    else:
        visual = '<div class="anno__cover anno__cover--mono"><span>%s</span></div>' % html.escape(
            e["title"][:2].upper())
    return ('<a class="anno cat-{cat}" href="/titles/{slug}.html">{visual}'
            '<div class="anno__body"><div class="anno__meta"><span class="anno__type">{icon}{note}</span>'
            '{catsfx}</div>'
            '<h3 class="anno__title">{title}</h3>'
            '<div class="anno__plat">{plats}</div></div></a>').format(
        cat=e["category"], visual=visual, icon=_cal_icon(e["kind_note"]), slug=e["slug"],
        catsfx=('<span class="anno__cat">%s</span>' % CAT_NAME.get(e["category"], e["category"]))
                   if not _same_as_category(e) else "",
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
        body = ('<section class="cal-week"><div class="rubric__head"><h2>Релизы на этой неделе</h2>'
                '<span class="rubric__all">%d %s</span></div><div class="cal">%s</div></section>'
                % (len(week), plural(len(week), "релиз", "релиза", "релизов"), "".join(blocks)))
        desc = ("Календарь анонсов: %d %s на этой неделе с подтверждёнными датами — "
                "игры, платформы, фильмы и сериалы. %s") % (
            len(week), plural(len(week), "релиз", "релиза", "релизов"), SITE["tagline"])

    # «Громкие релизы месяца»: тот же месяц, но дальше недели. Каждый месяц — свой блок,
    # поэтому прошлый месяц не исчезает, а спускается в блок истории.
    this_month = [e for e in entries if (e["day"] - today).days > 6
                  and (e["day"].year, e["day"].month) == (today.year, today.month)]
    past_months = {}
    for e in entries:
        if e["day"] < today:
            past_months.setdefault((e["day"].year, e["day"].month), []).append(e)
    later_months = {}
    for e in entries:
        if (e["day"] - today).days > 6 and (e["day"].year, e["day"].month) != (today.year, today.month):
            later_months.setdefault((e["day"].year, e["day"].month), []).append(e)

    def month_rows(items):
        return "".join(
            '<a class="mrow cat-%s" href="%s"><span class="mrow__d">%02d</span>'
            '<span class="mrow__t">%s</span><span class="mrow__p">%s</span></a>'
            % (e["category"], e["href"], e["day"].day, html.escape(e["title"]), _plat_tags(e["platforms"]))
            for e in sorted(items, key=lambda x: (x["day"], x["title"])))

    if this_month:
        body += ('<section class="cal-month"><div class="rubric__head"><h2>Громкие релизы %s</h2>'
                 '<span class="rubric__all">%d %s</span></div>%s</section>'
                 % (MONTHS_GEN_MONTH[today.month - 1], len(this_month),
                    plural(len(this_month), "релиз", "релиза", "релизов"), month_rows(this_month)))

    if later_months:
        mblocks = "".join(
            '<section class="mblock"><h3 class="mblock__h">%s %d</h3>%s</section>'
            % (MONTHS_NOM[m - 1], y, month_rows(later_months[(y, m)]))
            for (y, m) in sorted(later_months))
        body += ('<section class="cal-later"><div class="rubric__head"><h2>Дальше по календарю</h2>'
                 '<span class="rubric__all">%d %s</span></div>%s</section>'
                 % (sum(len(v) for v in later_months.values()),
                    plural(sum(len(v) for v in later_months.values()), "дата", "даты", "дат"), mblocks))

    if past_months:
        pblocks = "".join(
            '<section class="mblock mblock--past"><h3 class="mblock__h">%s %d</h3>%s</section>'
            % (MONTHS_NOM[m - 1], y, month_rows(past_months[(y, m)]))
            for (y, m) in sorted(past_months, reverse=True))
        body += ('<section class="cal-later cal-history"><div class="rubric__head"><h2>История</h2></div>%s</section>'
                 % pblocks)

    content = ('<main class="wrap">' + back_link("На главную", "/") + '<section class="lead"><h1>Календарь анонсов</h1>'
               '<p>Что выходит на этой неделе и что уже назначено дальше. Только подтверждённые даты.</p></section>'
               '%s</main>') % body
    return page("Календарь анонсов — релизы недели и месяца | %s" % SITE["title"], desc, content, theme,
                canonical=SITE["url"] + "/calendar/",
                jsonld=ldjson(ld_org(), ld_website(),
                              {"@type": "CollectionPage", "@id": SITE["url"] + "/calendar/#page",
                               "url": SITE["url"] + "/calendar/", "name": "Календарь анонсов",
                               "description": desc, "inLanguage": "ru-RU",
                               "isPartOf": {"@id": WEBSITE_ID}},
                              calendar_itemlist(entries),
                              ld_breadcrumb([("Главная", "/"), ("Календарь анонсов", "/calendar/")])))


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


TITLES = {}
ALL_POSTS = []   # все материалы и дайджесты: нужны для обратной перелинковки
CAL_ENTRIES = []   # заполняется в build(): записи календаря для страниц тайтлов
AUTHORS = []       # заполняется в build(): паспорта редакции из content/authors
AUTHOR_BY_CAT = {}  # рубрика → паспорт автора, который её ведёт


def load_titles():
    """content/titles/*.md — база игр, фильмов и сериалов. Ключ — слаг заголовка."""
    out = {}
    d = ROOT / "content" / "titles"
    if not d.exists():
        return out
    for f in sorted(d.glob("*.md")):
        rec = parse_post(f)          # frontmatter + текст как summary-тело
        slug = rec["slug"] if rec.get("slug") else f.stem
        out[slug] = {
            "slug": slug,
            "kind": rec["kind"] if rec["kind"] in ("game", "film", "series") else "game",
            "title": rec["title"],
            "year": rec["meta"].get("year", ""),
            "genre": rec["meta"].get("genre", ""),
            "developers": rec["meta"].get("developer", ""),
            "platforms": rec["meta"].get("platforms", ""),
            "links": rec["meta"].get("links", ""),
            "cover": rec["cover"],
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
    # даты из календаря: ближайшая будущая
    rel = [e for e in CAL_ENTRIES if e["slug"] == slug and e["day"] >= datetime.now().date()]
    when = ""
    if rel:
        e = sorted(rel, key=lambda x: x["day"])[0]
        when = ('<div class="tp__when">Выходит <b>%d %s</b></div>'
                % (e["day"].day, MONTHS_GEN[e["day"].month - 1]))
    mentions = articles_for_title(slug)
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
        ('<section class="sources"><h2>Источники</h2><ul>%s</ul></section>' % srcs) if srcs else "",
        share_block(SITE["url"] + "/titles/%s.html" % slug, t["title"], t["cover"] or DEFAULT_OG),
        ment_block)
    content = content.replace('<main class="wrap"><article class="tp">',
                              '<main class="wrap">' + back_link("К календарю", "/calendar/") + '<article class="tp">', 1)
    return page("%s — %s | %s" % (t["title"], {"game": "игра", "series": "сериал"}.get(t["kind"], "фильм"),
                                  SITE["title"]),
                plain(t["body"], 180), content, theme,
                canonical=SITE["url"] + "/titles/%s.html" % slug,
                og_image=t["cover"] or DEFAULT_OG,
                jsonld=ldjson(ld_org(), ld_website(), ld_title(t, slug),
                              ld_breadcrumb([("Главная", "/"), ("Календарь анонсов", "/calendar/"),
                                             (t["title"], "/titles/%s.html" % slug)])))


def ld_title(t, slug):
    """Разметка страницы тайтла: VideoGame / Movie / TVSeries.

    Именно на такие страницы опирается ответ «когда выходит <название>»:
    в разметке есть дата релиза из календаря, жанр, студия и издатель.
    """
    url = "%s/titles/%s.html" % (SITE["url"], slug)
    kind = {"game": "VideoGame", "film": "Movie", "series": "TVSeries"}.get(t["kind"], "CreativeWork")
    obj = {"@type": kind, "@id": url + "#entity", "name": t["title"], "url": url,
           "inLanguage": "ru-RU", "description": plain(t["body"], 200) or None}
    if t["cover"]:
        entry = {"@type": "ImageObject", "url": SITE["url"] + t["cover"]}
        size = image_size(local_image(SITE["url"] + t["cover"]) or Path("/nonexistent"))
        if size:
            entry["width"], entry["height"] = size
        obj["image"] = entry
    if t["genre"]:
        obj["genre"] = [g.strip() for g in re.split(r"[,/]", t["genre"]) if g.strip()]
    for key, meta_key in (("productionCompany", "developer"), ("publisher", "publisher")):
        name = (t.get("meta") or {}).get(meta_key) or t["developers"]
        if name:
            obj[key] = {"@type": "Organization", "name": name}
    # подтверждённая дата релиза из календаря (ближайшая будущая или последняя прошедшая)
    days = sorted(e["day"] for e in CAL_ENTRIES if e.get("slug") == slug)
    if days:
        today = datetime.now().date()
        future = [d for d in days if d >= today]
        obj["datePublished"] = (future[0] if future else days[-1]).strftime("%Y-%m-%d")
    return {k: v for k, v in obj.items() if v is not None}


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
                "slug": it.get("slug") or title_slug(it["title"]),
                "platforms": it.get("platforms", ""), "kind_note": it.get("kind_note", ""),
                "summary": it["summary"], "source": it["source"],
                "href": "/titles/%s.html" % (it.get("slug") or title_slug(it["title"])),
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
        ("accent", "#377BF0", "акцент (синий из логотипа)"),
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
                  '<p class="sg-hint">Инлайн-SVG 24×24, цвет наследуется от рубрики. Иконки бренда:</p>'
                  '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:16px;margin-top:8px;'
                  'font-size:var(--fs-meta);color:var(--muted)">'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/favicon.svg" alt="" width="18" height="18">favicon</span>'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/geekovski-icon.svg" alt="" width="18" height="18">знак</span>'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/geekovski-logo.svg" alt="" width="73" height="14" '
                  'style="background:#0A0C0F;padding:3px 6px;border-radius:4px">лого на тёмном</span>'
                  '<span style="display:flex;align-items:center;gap:6px">'
                  '<img src="/assets/img/geekovski-logo-light.svg" alt="" width="73" height="14" '
                  'style="background:#fff;padding:3px 6px;border-radius:4px">лого на светлом</span>'
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

MONTHS_GEN_MONTH = ["января", "февраля", "марта", "апреля", "мая", "июня",
                   "июля", "августа", "сентября", "октября", "ноября", "декабря"]
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
    return page(title_tag(head_title), d["summary"] or meta, content, theme,
                canonical=url, og_type="article", article=d, og_alt=head_title,
                jsonld=ldjson(ld_org(), ld_website(), ld_article(d, url),
                              ld_breadcrumb([("Главная", "/"), ("Дайджесты", "/digests/"),
                                             (head_title, "/digests/%s.html" % d["slug"])])))


def _digest_calendar(digests):
    """Календарь выпусков на две недели: сегодня и шесть дней вперёд + следующая неделя.

    Квадратные ячейки 7×2, точки — выпуски (лайм — утренний, фиолетовый —
    вечерний), клик по дню показывает этот день в панели под сеткой.
    Стрелки листают окно на неделю. Данные — JSON в странице, без запросов.
    """
    data = []
    for d in digests:
        data.append({
            "d": d["date"].strftime("%Y-%m-%d"),
            "p": part_of_day(d["date"]).upper(),
            "t": sentence_case(strip_prefix(d["title"])),
            "u": "/digests/%s.html" % d["slug"],
            "n": len(d["items"]),
        })
    payload = json.dumps(data, ensure_ascii=False)
    return """<div class="stripx" id="dcal">
  <button class="stripx__nav" type="button" id="sxPrev" aria-label="Предыдущая неделя">←</button>
  <div class="stripx__range" id="sxRange"></div>
  <button class="stripx__nav" type="button" id="sxNext" aria-label="Следующая неделя">→</button>
  <div class="stripx__wd" id="sxWd"></div>
  <div class="stripx__row" id="sxGrid"></div>
  <div class="stripx__panel" id="sxPanel" style="grid-column:1/-1"></div>
</div>
<script>
(function () {
  var DATA = %s;
  var grid = document.getElementById("sxGrid");
  var panel = document.getElementById("sxPanel");
  var range = document.getElementById("sxRange");
  var wdBox = document.getElementById("sxWd");
  var byDate = {};
  DATA.forEach(function (x) { (byDate[x.d] = byDate[x.d] || []).push(x); });
  var WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  var MG = ["января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  wdBox.innerHTML = WD.map(function (w) { return '<span class="stripx__w">' + w + "</span>"; }).join("");

  function midnight(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
  function addDays(d, n) { var x = new Date(d.getTime()); x.setDate(x.getDate() + n); return midnight(x); }
  function iso(d) { return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }

  var today = midnight(new Date());
  var start = addDays(today, -((today.getDay() + 6) %% 7));

  function rangeText(a, b) {
    if (a.getMonth() === b.getMonth()) {
      return a.getDate() + "–" + b.getDate() + " " + MG[b.getMonth()];
    }
    return a.getDate() + " " + MG[a.getMonth()] + " – " + b.getDate() + " " + MG[b.getMonth()];
  }

  function panelFor(isoDate) {
    var items = byDate[isoDate] || [];
    if (!items.length) { panel.innerHTML = ""; panel.style.display = "none"; return; }
    var d = new Date(isoDate + "T00:00:00");
    var html = '<div class="stripx__ptitle">' + d.getDate() + " " + MG[d.getMonth()] + "</div>";
    items.forEach(function (x) {
      html += '<a class="stripx__item" href="' + x.u + '">' +
              '<span class="stripx__part">' + x.p + "</span>" +
              '<span class="stripx__name">' + x.t + "</span>" +
              '<span class="stripx__count">' + x.n + "</span></a>";
    });
    panel.innerHTML = html;
    panel.style.display = "";
  }

  function render(pick) {
    range.textContent = rangeText(start, addDays(start, 13));
    var html = "";
    var lastHas = null;
    for (var i = 0; i < 14; i++) {
      var day = addDays(start, i), k = iso(day), items = byDate[k];
      var cls = "stripx__cell" + (items ? " has" : "") +
                (k === iso(today) ? " today" : "") + (i > 6 ? " next" : "");
      var dots = "";
      if (items) {
        lastHas = k;
        var morning = false, evening = false;
        items.forEach(function (x) { if (x.p === "ВЕЧЕР") evening = true; else morning = true; });
        if (morning) dots += '<i class="stripx__dot"></i>';
        if (evening) dots += '<i class="stripx__dot is-evening"></i>';
      }
      html += '<button type="button" class="' + cls + '" data-date="' + k + '"' +
              (items ? "" : " disabled") + '><span class="stripx__n">' + day.getDate() +
              '</span><span class="stripx__dots">' + dots + "</span></button>";
    }
    grid.innerHTML = html;
    grid.querySelectorAll(".stripx__cell.has").forEach(function (b) {
      b.addEventListener("click", function () {
        grid.querySelectorAll(".stripx__cell.active").forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        panelFor(b.dataset.date);
      });
    });
    var want = pick && byDate[pick] ? pick : lastHas;
    if (want) {
      var el = grid.querySelector('[data-date="' + want + '"]');
      if (el) { el.classList.add("active"); panelFor(want); return; }
    }
    panel.innerHTML = ""; panel.style.display = "none";
  }

  document.getElementById("sxPrev").addEventListener("click", function () { start = addDays(start, -7); render(); });
  document.getElementById("sxNext").addEventListener("click", function () { start = addDays(start, 7); render(); });
  var q = (location.search.match(/[?&]date=(\d{4}-\d{2}-\d{2})/) || [])[1];
  if (q) { start = addDays(new Date(q + "T00:00:00"), -((new Date(q + "T00:00:00").getDay() + 6) %% 7)); }
  render(q);
})();
</script>""" % payload


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
    content = ('<main class="wrap">' + back_link("На главную", "/") + '<section class="lead"><h1>Дайджесты</h1>'
               '<p>Коротко о том, что произошло — утром в 9 и вечером в 19. Из самого интересного потом выходят большие статьи в блоге.</p>'
               '</section>'
               '<div class="dviews" id="dviews">'
               '<div class="dviews__tabs" role="tablist">'
               '<button type="button" class="dviews__tab is-on" data-view="list">Список</button>'
               '<button type="button" class="dviews__tab" data-view="cal">Календарь</button>'
               '</div>'
               '<div class="dviews__pane" data-pane="list"><div class="dlist">%s</div></div>'
               '<div class="dviews__pane" data-pane="cal" hidden>%s</div>'
               '</div>'
               '<script>(function(){var w=document.getElementById("dviews"),'
               't=w.querySelectorAll(".dviews__tab"),p=w.querySelectorAll(".dviews__pane");'
               'function set(v){t.forEach(function(b){b.classList.toggle("is-on",b.dataset.view===v)});'
               'p.forEach(function(x){x.hidden=x.dataset.pane!==v});'
               'try{localStorage.setItem("digestView",v)}catch(e){}}'
               't.forEach(function(b){b.addEventListener("click",function(){set(b.dataset.view)})});'
               'var saved="list";try{saved=localStorage.getItem("digestView")||"list"}catch(e){}set(saved);})();</script>'
               '</main>') % ("".join(rows) or "<p>Пока пусто.</p>", _digest_calendar(digests))
    url = SITE["url"] + "/digests/"
    desc = ("Дайджесты GEEKOVSKI: короткие выпуски новостей игр, техники, кино и AI с ссылками "
            "на первоисточники. Выпусков в архиве: %d." % len(digests))
    return page("Дайджесты — короткие новости GEEKOVSKI", desc, content, theme,
                canonical=url, og_alt="Дайджесты GEEKOVSKI",
                digest_css="<style>%s</style>\n<style>%s</style>" % (DIGEST_VIEW_CSS, DIGEST_HIDE_LEAD),
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
    vk_items = vk_selection(ps)
    print("vk.xml: %d анонсов (%s)" % (len(vk_items), ", ".join(p["slug"] for p in vk_items)))
    problems = image_report(ps)
    if problems:
        print("\nкартинки: проблем %d" % len(problems))
        for line in problems:
            print("  ·", line)
        if a.strict_images:
            raise SystemExit(1)
    else:
        print("картинки: повторов нет")

