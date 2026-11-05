---
title: Unreal Engine 6 останется без Blueprints
date: 2026-11-05 12:05
category: pc
summary: На Unreal Fest Tokyo Тим Суини показал, что в UE6 Blueprints, Actors и C++ Gameplay Framework будут удалены, а не отложены в долгий ящик: игровая логика переезжает в Verse. Epic это письменно не подтверждала.
tldr: На слайдах Unreal Fest Tokyo три системы помечены «Remove», а не «deprecated» — Blueprints, Actors и C++ Gameplay Framework | Игровая логика в UE6 переходит в Verse, сцены собираются в Scene Graph | Это разворот июньского плана: тогда Blueprints обещали оставить в первых версиях | UE6 Early Access ожидается в конце 2027 года, проекты на UE5 остаются на ветке UE5
cover: /assets/img/unreal-engine-6-bez-blueprintov.jpg
credit: Обложка: GEEKOVSKI. Фото: Pexels / Nemuel Sereti
sources: Inven Global — Epic Games will remove Blueprints and Actors from Unreal Engine 6 | https://www.invenglobal.com/articles/28098/epic-games-will-remove-blueprints-and-actors-from-unreal-engine-6; Digital Developer — Unreal Fest Tokyo: UE6 to remove Blueprints and C++ Gameplay Framework | https://www.digitaldeveloper.io/article/unreal-fest-tokyo-ue6-to-remove-blueprints-and-c-gameplay-framework; AIGamer — Report: Unreal Engine 6 drops Blueprints and Actors | https://www.aigamer.gg/news/unreal-engine-6-drops-blueprints-actors-verse; Game Developer — Unreal Engine 6 will merge UE5 and UEFN into one engine | https://www.gamedeveloper.com/programming/unreal-engine-6-will-merge-ue5-and-uefn-into-a-single-unified-engine-
---

3 ноября на Unreal Fest Tokyo Тим Суини показал планы по Unreal Engine 6, и главное в них — не добавление, а удаление. На слайдах ключевого доклада Blueprints, Actors и C++ Gameplay Framework помечены словом «Remove», а не «deprecated»: то есть их не будут постепенно выводить, их не будет с самого начала. Об этом сообщил японский Game Makers, пересказали Inven Global и Automaton. Важная оговорка: Epic письменно этот план не публиковала, всё сказанное — пересказ доклада и пресс-брифинга, официального документа на момент публикации нет.

Что приходит на место. Игровая логика переезжает в Verse — язык, который Epic уже обкатала в Unreal Editor for Fortnite. Сцены собираются не из акторов, а в Scene Graph: сущности из компонентов. Добавляются новые Verse Gameplay APIs, а сборка через MCP и Python становится штатной. C++ из движка не исчезает, но остаётся в нижних слоях — рендер, физика — и в игровом фреймворке больше не используется.

Это разворот июньского решения. На Unreal Fest Chicago и в записи «The road to Unreal Engine 6» Epic говорила ровно обратное: Actors и Blueprints останутся в первых версиях UE6 и будут выведены позже, когда новый фреймворк созреет. Теперь их убирают сразу, а Early Access UE6 по-прежнему ждут в конце 2027 года.

Причина, которую называет Суини, — производительность и AI. В докладе говорилось, что внутри Epic AI-инструменты ускорили программирование, отладку и левел-дизайн в 1,5–4 раза; эти цифры — внутренние оценки компании, проверить их снаружи нельзя. Для переезда обещаны AI-инструменты конвертации Blueprints и C++ в Verse, но в каком виде их выдадут, не решено. Epic проходит этот путь первой: Fortnite переносит тысячи Blueprints и остатки C++ игровой логики на Verse. Суини назвал решение «болезненным изменением» и извинился перед теми, кто любит Blueprints.

Что делать тем, кто уже в разработке: проекты на UE5 остаются на ветке UE5, включая 5.9 и следующие 5.x — превью 5.9 выходило на неделе после конференции. В X Суини в тот же день написал, что ведущие модели «мало видели Verse в процессе обучения, но к январю это изменится», и что команды могут брать любую модель — или не брать ни одной.

Мнение: для студий с армией C++-программистов это техническая новость, а для инди и одиночек — смена входного билета. Blueprints годами были способом делать игры в Unreal вообще без кода; Verse с AI-подсказками вместо визуальных графов — другой навык, и не факт, что он проще. Ставка Epic на AI понятна, но она делает Unreal менее доступным ровно для той аудитории, на которой движок и вырос.
