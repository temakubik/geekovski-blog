# GEEKOVSKI — блог на GitHub Pages

Статический сайт: заметки лежат в `content/posts/*.md`, генератор `build.py` собирает
готовый HTML в `docs/`, GitHub Pages раздаёт содержимое `docs/`.

## Как выпустить заметку

1. Создать файл `content/posts/<slug>.md`:

```
---
title: Заголовок
date: 2026-11-05 10:30
category: igry          # gadgets | kino | igry | ai
summary: Одно-два предложения лида.
cover:                          # /assets/img/xxx.jpg, если есть картинка
sources: Название — url | https://...; Второе издание | https://...
---

Текст в markdown. `## Заголовок раздела` — подзаголовок, `- пункт` — список,
**жирный**, *курсив*, [ссылка](https://...).
```

2. Собрать и проверить локально:

```
python3 build.py --theme editorial
cd docs && python3 -m http.server 8000
```

3. Закоммитить и запушить — Pages пересоберётся сам (30–60 секунд).

```
git add -A && git commit -m "post: <slug>" && git push
```

## Тема оформления

`--theme editorial|dashboard|magazine`. Выбранная тема фиксируется в `Makefile`/команде сборки.

## Первый деплой (один раз)

1. Репозиторий `geekovski-blog` (public — Pages на бесплатном тарифе работает только там).
2. Settings → Pages → Source: **Deploy from a branch**, Branch: `main`, папка **/docs**.
3. Custom domain: `geekovski.ru` (без `https://`), Save. GitHub создаст файл `CNAME` в `docs/`.
4. Дождаться DNS check, включить **Enforce HTTPS**.
5. Settings → Pages → **Verify domain** → добавить в DNS TXT-запись
   `_github-pages-challenge-temakubik` со значением из окна → Verify. Запись не удалять.

## DNS (зона живёт на NS sprinthost: ns1–ns4.sprinthost.ru)

Правится в панели SprintHost (домен добавлен туда), либо переключением NS на REG.RU и
правкой в личном кабинете регистратора. Нужно:

| Тип | Имя | Значение |
|-----|-----|----------|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | temakubik.github.io. |
| TXT | _github-pages-challenge-temakubik | (из окна Verify domain) |

Старую A-запись `109.196.165.85` удалить. Wildcard `*` не добавлять — риск захвата домена.
