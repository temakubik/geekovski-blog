---
title: Unreal Engine 6 без Blueprints: что Epic подтвердила и как быть с UE5
date: 2026-11-05 12:05
updated: 2026-11-24 11:05
category: pc
summary: Epic подтвердила, что в Unreal Engine 6, включая ранний доступ, не будет Blueprints и Actor Gameplay Framework. Разбираем переход на Verse и что делать с проектом на UE5.
tldr: Epic подтвердила отказ от Blueprints и Actor Gameplay Framework уже в раннем доступе UE6 | Игровая логика переходит на Verse и Scene Graph | Проекты можно оставить на UE5: Epic обещает продолжать поддержку ветки
cover: /assets/img/unreal-engine-6-bez-blueprintov.jpg
pin: /assets/img/unreal-engine-6-bez-blueprintov-pin.jpg
credit: Обложка: GEEKOVSKI. Фото: Pexels / Nemuel Sereti
sources: Epic Games — An update on Blueprints and the path to UE6 | https://www.unrealengine.com/news/an-update-on-blueprints-and-the-path-to-ue6; Epic Games Japan — итоги Unreal Fest Tokyo 2026 | https://prtimes.jp/main/html/rd/p/000000211.000036502.html
---
Epic Games официально подтвердила, что **в Unreal Engine 6, включая ранний доступ, не будет Blueprints и Actor Gameplay Framework**. Игровую логику предлагают писать на Verse, а сцены собирать на Scene Graph. Если ваш проект уже на UE5, Epic оставляет решение о переходе за вами. Blueprint-систему в UE5 продолжают поддерживать.

## Что изменилось после Unreal Fest Tokyo

В июне Epic рассчитывала сохранить Blueprints и Actors на этапе раннего доступа и в UE 6.0, чтобы студии могли переезжать постепенно. На Unreal Fest Tokyo компания показала другой план. Позднее Epic закрепила его в [разъяснении для разработчиков](https://www.unrealengine.com/news/an-update-on-blueprints-and-the-path-to-ue6).

Epic объясняет поворот тем, что стала рассчитывать на ИИ при переносе игровых систем. Внутри компании таким способом сделали рабочий прототип Fortnite Battle Royale на Verse, перенёсши более 20 тысяч Blueprints. Команда всё ещё проверяет производительность, расход памяти и архитектуру прототипа. Из этого эксперимента пока рано делать выводы о стоимости переноса стороннего проекта или о том, какие инструменты получат разработчики.

## Что делать, если проект уже на UE5

- **Для проекта в производстве** можно оставить выбранную версию UE5. Epic обещает продолжать выпускать целевые улучшения, исправления и поддержку этой ветки.
- **Для оценки перехода** сначала выпишите критичные Blueprint-системы и плагины. Когда будет доступна подходящая сборка UE6, проверьте перенос одного характерного игрового сценария отдельно от основного проекта.
- **Для знакомства с новым подходом** уже можно посмотреть Verse и Scene Graph в UEFN. Часть инструментов из UE6 Epic начала переносить в превью UE 5.9, включая расширенный доступ к редактору через Python.

Для небольшой команды, привыкшей к визуальным графам, переход означает освоение нового языка и проверку собственных инструментов. Оценивать его стоит по тому, сколько работы займёт перенос именно вашей игры.
