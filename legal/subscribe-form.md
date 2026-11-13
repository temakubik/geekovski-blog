# Форма подписки — разметка

Готовая HTML-разметка формы с двумя раздельными галочками. Вставить в статью или на отдельную страницу.

## CSS (добавить в тему)

```css
.subscribe { margin: 34px 0; padding: 24px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel); }
.subscribe h2 { font-family: "Chava", sans-serif; font-size: 20px; letter-spacing: .04em; margin: 0 0 8px; font-weight: 400; text-transform: uppercase; }
.subscribe p { color: var(--muted); font-size: 14px; margin: 0 0 16px; }
.subscribe label.field { display: block; font-family: "Medeo Mono", monospace; font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }
.subscribe input[type=email] { width: 100%; padding: 11px 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 3px; color: var(--text); font: inherit; }
.subscribe input[type=email]:focus { outline: none; border-color: var(--accent); }
.subscribe .check { display: flex; gap: 9px; align-items: flex-start; margin-top: 12px; font-size: 12.5px; line-height: 1.45; color: var(--muted); }
.subscribe .check input { margin-top: 3px; accent-color: var(--accent); }
.subscribe .check a { color: var(--text); text-decoration: underline; text-underline-offset: 2px; }
.subscribe button { margin-top: 16px; width: 100%; padding: 12px; border: 0; border-radius: 3px; background: var(--accent); color: #0A0C0F; font-family: "Medeo Mono", monospace; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; cursor: pointer; }
.subscribe button:disabled { opacity: .5; cursor: not-allowed; }
.subscribe .note { margin-top: 10px; font-size: 12px; color: var(--muted); }
```

## HTML

```html
<form class="subscribe" id="subscribe"
      action="https://FORM-ENDPOINT" method="post">
  <h2>Дайджест GEEKOVSKI</h2>
  <p>Дважды в день, коротко и по делу. Отписаться можно в один клик.</p>

  <label class="field" for="sub-email">Email</label>
  <input id="sub-email" type="email" name="email" required autocomplete="email" placeholder="you@example.com">

  <!-- согласие на обработку ПДн — отдельный документ, чекбокс пустой -->
  <label class="check">
    <input type="checkbox" name="consent_pd" value="1" required>
    <span>Даю <a href="/consent.html" target="_blank" rel="noopener">согласие на обработку персональных данных</a>
      на условиях <a href="/privacy.html" target="_blank" rel="noopener">политики</a>.</span>
  </label>

  <!-- отдельное согласие на рекламные сообщения — необязательное -->
  <label class="check">
    <input type="checkbox" name="consent_ads" value="1">
    <span>Согласен получать <a href="/marketing-consent.html" target="_blank" rel="noopener">рекламные сообщения</a>
      (анонсы и предложения партнёров). Необязательно.</span>
  </label>

  <button type="submit">Подписаться</button>
  <div class="note">Данные хранятся в РФ. Отписка в любом письме.</div>

  <!-- служебное: фиксация факта согласия -->
  <input type="hidden" name="consent_ts" id="consent_ts">
  <input type="hidden" name="consent_version" value="2026-11">
  <input type="hidden" name="page" value="">
</form>

<script>
document.getElementById('subscribe').addEventListener('submit', (e) => {
  document.getElementById('consent_ts').value = new Date().toISOString();
  document.querySelector('input[name=page]').value = location.pathname;
});
</script>
```

## Где принимать данные

| Сервис | Серверы | Подходит для 152-ФЗ |
|---|---|---|
| **Республика (Tilda)** | РФ | да, если подключить блок и складывать в Tilda CRM |
| **Яндекс Формы** | РФ | да |
| **Cloudflare Worker → Telegram/Supabase** | зависит от базы | да, если база в РФ |
| Formspree / Google Forms / Mailchimp | за рубежом | ❌ нарушает локализацию (ч. 5 ст. 18) |

В `action` подставить эндпоинт выбранного сервиса.

## Что должно уйти на сервер

- `email`, `consent_pd` (1), `consent_ads` (1 или 0);
- `consent_ts` — момент отметки;
- `consent_version` — версия документов (при правке политики меняется);
- `page` — откуда подписались.

Эти пять полей — доказательство законного согласия при проверке.

## Обязательные страницы

- `/privacy.html`
- `/consent.html`
- `/marketing-consent.html`

Все три лежат в `legal/` и подставляются в сборку как обычные страницы сайта.
