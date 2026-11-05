---
title: OpenAI покупает Pierre — Codex получит свой GitHub
date: 2026-11-05 11:14
category: ai
summary: 4 ноября OpenAI объявила о покупке Pierre Computer Company — компании за Code Storage и open-source библиотеками Trees, Diffs и Highlights, которые уже работают в приложении Codex. Сделку ещё не закрыли.
tldr: OpenAI подписала соглашение о покупке Pierre Computer Company, сумма не раскрыта | Библиотеки Pierre (Trees, Diffs, Highlights) уже используются в Codex, Code Storage хранит код поверх Git | Сделка не закрыта — нужны регуляторные одобрения, до закрытия компании независимы | Axios называет это заходом на GitHub; open-source проекты Pierre останутся открытыми
cover: /assets/img/openai-pokupaet-pierre.jpg
pin: /assets/img/openai-pokupaet-pierre-pin.jpg
credit: Обложка: GEEKOVSKI. Фото: Markus Spiske / Unsplash, CC0
sources: OpenAI — OpenAI to acquire Pierre Computer Company, Inc. | https://openai.com/index/openai-to-acquire-pierre/; Axios — OpenAI targets Microsoft's GitHub with deal for startup | https://www.axios.com/2026/11/04/openai-pierre-computer-github; The Decoder — OpenAI acquires Pierre Computer Company | https://the-decoder.com/openai-acquires-pierre-computer-company-to-make-git-keep-up-with-ai-coding-agents/; WSJ — OpenAI to Bring Pierre Computer's Code Storage to Codex | https://www.wsj.com/tech/ai/openai-to-bring-pierre-computers-code-storage-to-codex-through-acquisition-05f53582
---

4 ноября OpenAI объявила, что договорилась купить Pierre Computer Company, Inc. — стартап, стоящий за сервисом Code Storage и набором open-source инструментов для работы с кодом. Это не закрытая сделка: в записи блога прямо сказано, что она подлежит стандартным условиям закрытия, включая регуляторные одобрения, а до закрытия обе компании остаются независимыми. Сумму не назвали.

OpenAI не покупает что-то абстрактное. Библиотеки Pierre уже работают внутри Codex: Trees отвечает за быструю навигацию по файлам проекта, Diffs показывает изменения и позволяет править строку прямо в диффе, Highlights подсвечивает синтаксис в реальном времени — и когда пишет человек, и когда код генерирует агент. Code Storage, коммерческий продукт, хранит код и его историю поверх Git.

Мотив сформулирован в самом объявлении: инфраструктура вокруг Git не рассчитана на то, что код одновременно пишут много людей и много агентов. «От первой ветки, которую создаёт агент, до момента, когда код уходит в мир» — так OpenAI описывает задачу, которую хочет закрыть вместе с командой Pierre. Open-source проекты останутся open-source, и OpenAI обещает продолжать в них контрибутить.

Axios первым сообщил о сделке и сразу расставил акценты: это заход на территорию GitHub, который принадлежит Microsoft — крупному инвестору самой OpenAI. Стоит держать в голове, что Code Storage — это не полноценная замена GitHub с пулл-реквестами, обсуждениями и релизами. Пока речь о слое хранения и навигации в коде, который нужен агентским инструментам внутри Codex.

Оценка: это ставка на то, что разработчик будущего будет работать не в браузере на github.com, а в редакторе и агенте, а репозиторий станет для него инфраструктурой под капотом. Если план сработает, GitHub не исчезнет, но перестанет быть обязательным пунктом маршрута. Если нет — OpenAI получит хороший набор библиотек и очень плохую репутацию после смены лицензий, которую никто пока не обсуждает.
