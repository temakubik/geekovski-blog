#!/usr/bin/env python3
"""Генерирует HTML фреймов страницы «Стили» для канвы Doop и раскладывает в /tmp/doop-styles/."""
import json
import pathlib

BASE = "https://geekovski.ru"
OUT = pathlib.Path("/tmp/doop-styles")
OUT.mkdir(exist_ok=True)

import base64

FDIR = pathlib.Path("/tmp/doop-styles/fonts")


def _b64(name):
    return base64.b64encode((FDIR / name).read_bytes()).decode()


# шрифты вшиты base64: у рендерера Doop нет доступа к внешней сети,
# иначе кадр молча уезжает на системный sans
FONTS = """
@font-face{font-family:'Chava';src:url(data:font/woff2;base64,%s) format('woff2');font-display:block}
@font-face{font-family:'RGS';src:url(data:font/woff2;base64,%s) format('woff2');font-display:block}
@font-face{font-family:'Medeo Sans';src:url(data:font/woff2;base64,%s) format('woff2');font-weight:100 900;font-display:block}
@font-face{font-family:'Medeo Mono';src:url(data:font/woff2;base64,%s) format('woff2');font-weight:100 900;font-display:block}
""" % (_b64("chava.woff2"), _b64("rgs.woff2"), _b64("sans.woff2"), _b64("mono.woff2"))

COMMON = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0A0C0F;color:#E9EBEE;font-family:'Medeo Sans',sans-serif;padding:44px 52px;
     -webkit-font-smoothing:antialiased}
.kicker{font-family:'Chava',monospace;font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#C9F24D}
h2.sec{font-family:'RGS';font-style:italic;font-weight:900;font-size:34px;letter-spacing:-.025em;margin:6px 0 26px}
.hint{font-family:'Medeo Mono',monospace;font-size:12px;color:#8B939E;letter-spacing:.02em}
.label{font-family:'Chava',monospace;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#8B939E}
.rule{border-top:1px solid #1F252E}
"""

ICONS = {
    "xbox": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M7 6.5c3 2.2 7 2.2 10 0M7 17.5c3-2.2 7-2.2 10 0"/></svg>',
    "switch": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="6" width="8" height="12" rx="4"/><rect x="13" y="6" width="8" height="12" rx="4"/><circle cx="7" cy="10" r="1.2"/><circle cx="17" cy="10" r="1.2"/></svg>',
    "playstation": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 4v13l5 3V7zM14 20l5-3V5l-5 3z"/></svg>',
    "pc": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="5" width="18" height="11" rx="1.5"/><path d="M8 20h8"/></svg>',
    "vr": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 9h18v5a3 3 0 0 1-3 3h-3l-3-3-3 3H6a3 3 0 0 1-3-3z"/></svg>',
    "gadgets": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 5.5h3"/></svg>',
    "kino": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M8 5v4M16 5v4"/></svg>',
    "serialy": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 3l4 4 4-4"/></svg>',
    "ai": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="6" y="6" width="12" height="12" rx="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>',
}

CAT_NAMES = [("xbox", "Xbox"), ("switch", "Nintendo Switch"), ("playstation", "PlayStation"),
             ("pc", "PC-игры"), ("vr", "VR"), ("gadgets", "Гаджеты"),
             ("kino", "Кино"), ("serialy", "Сериалы"), ("ai", "AI")]
CAT_COLORS = {"xbox": "#2FB344", "switch": "#E60012", "playstation": "#2F6DF6", "pc": "#8B5CF6",
              "vr": "#A855F7", "gadgets": "#22D3EE", "kino": "#F0553F", "serialy": "#F5A524", "ai": "#14B8A6"}


def doc(css_extra, body, w, h):
    return ("<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
            "<style>" + FONTS + COMMON + css_extra + "</style></head><body>" + body + "</body></html>")


# ---------------- 1. Типографика ----------------
def typography():
    rows = [
        ("H0 · заголовок статьи", "H0", "52 px · RGS 900 italic · -2.5%", "#E9EBEE",
         "<div style=\"font-family:'RGS';font-style:italic;font-weight:900;font-size:52px;line-height:1.1;letter-spacing:-.025em\">Убыток Anthropic</div>"),
        ("H1 · герой, H2 в тексте", "H1", "40 px · RGS 900 italic · -2%", "#E9EBEE",
         "<div style=\"font-family:'RGS';font-style:italic;font-weight:900;font-size:40px;line-height:1.12;letter-spacing:-.02em\">Ocarina of Time выходит 5 ноября</div>"),
        ("H2 · карточки, H3 в тексте", "H2", "24 px · RGS 900 italic · -1.5%", "#E9EBEE",
         "<div style=\"font-family:'RGS';font-style:italic;font-weight:900;font-size:24px;line-height:1.25;letter-spacing:-.015em\">Pikmin 4: демо уже в eShop</div>"),
        ("Лид", "LEAD", "17 px / 1.5 · Medeo Sans", "#8B939E",
         "<div style=\"font-size:17px;line-height:1.5;color:#8B939E\">Демо Pikmin 4 в eShop, Zelda выходит 5 ноября, Circana зафиксировала падение продаж.</div>"),
        ("Основной текст", "BODY", "16 px / 1.65 · Medeo Sans", "#E9EBEE",
         "<div style=\"font-size:16px;line-height:1.65\">Nintendo провела Pikmin Direct, предупредив за десять минут до эфира. Демо весит 4,1 ГБ и переносит сейв в полную версию.</div>"),
        ("Мелкий текст", "SMALL", "14 px / 1.45 · Medeo Sans", "#8B939E",
         "<div style=\"font-size:14px;line-height:1.45;color:#8B939E\">Стартовая зона и два экзамена Dandori Academy</div>"),
        ("Метка · капитель", "META", "12 px · Chava uppercase · +10%", "#8B939E",
         "<div style=\"font-family:'Chava',monospace;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#8B939E\">Nintendo Switch · 3 ноября</div>"),
    ]
    inner = "".join(
        "<div style='display:grid;grid-template-columns:250px 1fr;gap:26px;align-items:start;"
        "padding:20px 0;border-bottom:1px solid #1F252E'>"
        "<div><div class='label' style='color:#E9EBEE'>%s</div>"
        "<div class='hint' style='margin-top:6px'>%s</div>"
        "<div class='hint' style='color:#C9F24D;margin-top:4px'>--fs-%s</div></div>"
        "<div>%s</div></div>" % (name, spec, tok, sample)
        for name, tok, spec, _c, sample in rows)
    body = ("<div class='kicker'>GEEKOVSKI · Style Guide</div>"
            "<h2 class='sec'>Типографика</h2>" + inner +
            "<div style='margin-top:20px' class='hint'>Четыре гарнитуры: RGS (заголовки), Chava (капитель), "
            "Medeo Sans (текст), Medeo Mono (технические подписи). Прямых font-size в вёрстке нет — только токены.</div>")
    return doc("", body, 1200, 0)


# ---------------- 2. Палитра ----------------
def palette():
    def sw(name, hexv, note=""):
        return ("<div style='display:grid;grid-template-columns:30px 1fr;gap:2px 12px;align-items:center;"
                "padding:12px;border:1px solid #1F252E;border-radius:4px'>"
                "<span style='grid-row:span 2;width:30px;height:30px;border-radius:4px;background:%s;"
                "border:1px solid rgba(255,255,255,.14)'></span>"
                "<span style='font-size:14px'>%s</span>"
                "<span style='font-family:\"Medeo Mono\",monospace;font-size:12px;color:#8B939E'>%s %s</span></div>"
                % (hexv, name, hexv, note))

    base = [("ink", "#0A0C0F", "фон"), ("panel", "#11151A", "плашки"), ("line", "#1F252E", "разделители"),
            ("text", "#E9EBEE", "текст"), ("muted", "#8B939E", "второй план"), ("accent", "#C9F24D", "акцент")]
    body = ("<div class='kicker'>GEEKOVSKI · Style Guide</div><h2 class='sec'>Палитра</h2>"
            "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:12px'>"
            + "".join(sw(n, h, note) for n, h, note in base) + "</div>"
            "<div class='label' style='margin:26px 0 12px'>Рубрики</div>"
            "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:12px'>"
            + "".join(sw(n, CAT_COLORS[c]) for c, n in CAT_NAMES) + "</div>"
            "<div class='label' style='margin:26px 0 12px'>Время суток в дайджестах</div>"
            "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:12px'>"
            + sw("Утро", "#F5C518", "жёлтый") + sw("Вечер", "#A855F7", "фиолетовый")
            + "<div style='display:grid;grid-template-columns:30px 1fr;gap:2px 12px;align-items:center;"
              "padding:12px;border:1px solid #1F252E;border-radius:4px'>"
              "<span style='grid-row:span 2;width:30px;height:30px;border-radius:4px;background:linear-gradient("
              "135deg,#F5C518,#A855F7)'></span><span style='font-size:14px'>2 % на подложке</span>"
              "<span class='hint'>rgba(colour,.02)</span></div></div>")
    return doc("", body, 1200, 0)


# ---------------- 3. Теги и иконки ----------------
def tags_icons():
    chips = "".join(
        "<span style='font-family:\"Chava\",monospace;font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
        "color:%s;border:1px solid %s;padding:4px 8px;border-radius:2px'>%s</span>" % (CAT_COLORS[c], CAT_COLORS[c], n)
        for c, n in CAT_NAMES)
    solid = ("<span style='font-family:\"Chava\",monospace;font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
             "background:#C9F24D;color:#0A0C0F;padding:4px 8px;border-radius:2px'>Дайджест</span>")
    small = ("<span style='font-family:\"Chava\",monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;"
             "color:#8B939E;border:1px solid #1F252E;padding:2px 6px;border-radius:2px'>chip--sm</span>")
    icons = "".join(
        "<div style='display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid #1F252E;"
        "border-radius:4px;color:%s'><span style='display:flex'>%s</span>"
        "<span style='font-family:\"Medeo Sans\",sans-serif;font-size:13px;color:#E9EBEE'>%s</span></div>"
        % (CAT_COLORS[c], ICONS[c], n) for c, n in CAT_NAMES)
    body = ("<div class='kicker'>GEEKOVSKI · Style Guide</div><h2 class='sec'>Теги и иконки</h2>"
            "<div class='label' style='margin-bottom:12px'>Теги рубрик</div>"
            "<div style='display:flex;flex-wrap:wrap;gap:8px;padding:16px;border:1px solid #1F252E;"
            "border-radius:4px;background:#11151A'>" + chips + solid + small + "</div>"
            "<div class='hint' style='margin-top:10px'>Chava 12 px, uppercase, разрядка .08em. Цвет тега = цвет рубрики, не акцент.</div>"
            "<div class='label' style='margin:26px 0 12px'>Иконки рубрик · инлайн-SVG 24×24</div>"
            "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>" + icons + "</div>"
            "<div class='hint' style='margin-top:16px'>Бренд: favicon.svg + logo.svg. Сюда же кладём новые иконки — "
            "они затем уходят в словарь ICONS в build.py и в дайджесты.</div>")
    return doc("", body, 1200, 0)


# ---------------- 4. Компоненты ----------------
def components():
    card = ("<div style='border:1px solid #1F252E;border-radius:4px;padding:18px;background:#11151A'>"
            "<div style='display:flex;gap:10px;align-items:center;margin-bottom:10px'>"
            "<span style='font-family:\"Chava\",monospace;font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
            "color:#E60012;border:1px solid #E60012;padding:3px 7px;border-radius:2px'>Nintendo Switch</span>"
            "<span class='hint'>3 ноября</span></div>"
            "<div style=\"font-family:'RGS';font-style:italic;font-weight:900;font-size:24px;line-height:1.25\">Pikmin 4: демо уже в eShop</div>"
            "<div style='font-size:14px;color:#8B939E;margin:8px 0 12px;line-height:1.5'>Стартовая зона и два экзамена Dandori Academy, сейв переносится.</div>"
            "<div style='display:flex;justify-content:space-between;font-family:\"Chava\",monospace;font-size:12px;"
            "letter-spacing:.08em;text-transform:uppercase;color:#8B939E'><span>Читать →</span><span>2 источника</span></div></div>")

    item = ("<div style='display:grid;grid-template-columns:46px 1fr;gap:14px;padding:20px 0;border-bottom:1px solid #1F252E'>"
            "<div style='color:#E60012'><div class='hint'>01</div><div style='margin-top:8px'>%s</div></div>"
            "<div><div style='margin-bottom:6px'><span style='font-family:\"Chava\",monospace;font-size:10px;"
            "letter-spacing:.08em;text-transform:uppercase;color:#8B939E;border:1px solid #1F252E;padding:2px 6px;"
            "border-radius:2px'>Nintendo Switch</span></div>"
            "<div style=\"font-family:'RGS';font-style:italic;font-weight:900;font-size:24px;line-height:1.25;margin-bottom:8px\">Демо Pikmin 4 уже в eShop</div>"
            "<div style='font-size:14px;color:#8B939E;line-height:1.55;margin-bottom:8px'>Стартовая зона и два экзамена Dandori Academy.</div>"
            "<div style='font-family:\"Medeo Mono\",monospace;font-size:12px;text-decoration:underline;"
            "text-underline-offset:2px;opacity:.8'>Nintendo Life</div></div></div>" % ICONS["switch"])

    row = ("<div style='display:grid;grid-template-columns:max-content 1fr auto;gap:18px;align-items:start;"
           "padding:22px 18px;border:1px solid #1F252E;border-left:3px solid #A855F7;border-radius:4px;"
           "background:rgba(168,85,247,.02)'>"
           "<div style='display:flex;flex-direction:column;gap:4px'>"
           "<span style='font-family:\"Chava\",monospace;font-size:14px;color:#E9EBEE'>3 ноября</span>"
           "<span style='font-family:\"Chava\",monospace;font-size:12px;letter-spacing:.1em;color:#A855F7'>ВЕЧЕР</span></div>"
           "<div><div style=\"font-family:'RGS';font-style:italic;font-weight:900;font-size:24px;line-height:1.25;margin-bottom:8px\">"
           "Убыток Anthropic, Crimson Desert на PS5</div>"
           "<div style='font-size:14px;color:#8B939E;line-height:1.45'>Квартальная выручка $17 млрд, Crimson Desert снова не держит 30 fps.</div></div>"
           "<span class='hint' style='padding-top:3px'>6 новостей</span></div>")

    share = "".join(
        "<span style='font-family:\"Chava\",monospace;font-size:12px;letter-spacing:.06em;text-transform:uppercase;"
        "padding:7px 11px;border:1px solid #1F252E;border-radius:3px'>%s</span>" % s
        for s in ["Telegram", "VK", "WhatsApp", "X", "Pinterest", "Скопировать"])

    body = ("<div class='kicker'>GEEKOVSKI · Style Guide</div><h2 class='sec'>Компоненты</h2>"
            "<div class='label' style='margin-bottom:10px'>Карточка материала</div>" + card +
            "<div class='label' style='margin:26px 0 4px'>Новость в дайджесте</div>" + item +
            "<div class='label' style='margin:26px 0 10px'>Выпуск в списке дайджестов</div>" + row +
            "<div class='label' style='margin:26px 0 10px'>Поделиться</div>"
            "<div style='display:flex;flex-wrap:wrap;gap:8px'>" + share + "</div>")
    return doc("", body, 1200, 0)


if __name__ == "__main__":
    frames = {
        "sg-typography": typography(),
        "sg-palette": palette(),
        "sg-tags": tags_icons(),
        "sg-components": components(),
    }
    for name, html in frames.items():
        (OUT / (name + ".html")).write_text(html, encoding="utf-8")
        print(name, len(html))
