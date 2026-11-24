---
title: DLSS 5 в Hogwarts Legacy: как включить и какие видеокарты подходят
date: 2026-11-05 20:10
updated: 2026-11-24 11:05
category: pc
summary: Где включить Neural Rendering в Hogwarts Legacy, какой драйвер нужен для GeForce RTX 50 и как запустить DLSS 5 через GeForce NOW Ultimate.
tldr: Нейрорендеринг добавили в бесплатном обновлении PC-версии, по умолчанию он выключен | В настройках экрана выберите NVIDIA DLSS и включите Neural Rendering | Нужны GeForce RTX 50 с драйвером 616.64 или новее, ПК на RTX Spark либо GeForce NOW Ultimate
cover: /assets/img/hogwarts-legacy-dlss-5.jpg
pin: /assets/img/hogwarts-legacy-dlss-5-pin.jpg
credit: Обложка: GEEKOVSKI. Кадр: NVIDIA
sources: Portkey Games Support — как включить DLSS 5 в Hogwarts Legacy | https://portkeygamessupport.wbgames.com/hc/en-us/articles/56349775286419; NVIDIA — Hogwarts Legacy Adds DLSS 5 Neural Rendering | https://www.nvidia.com/en-us/geforce/news/hogwarts-legacy-war-thunder-dlss-5-3d-guided-neural-rendering/; NVIDIA — Hogwarts Legacy в GeForce NOW | https://blogs.nvidia.com/blog/geforce-now-thursday-hogwarts-legacy-dlss-5/
---
Нейрорендеринг DLSS 5 появился в [Hogwarts Legacy](/titles/hogwarts-legacy.html) с бесплатным обновлением PC-версии 5 ноября. По умолчанию он выключен. На совместимой системе его можно включить в настройках экрана.

## Как включить DLSS 5 в Hogwarts Legacy

1. Обновите игру в Steam, Epic Games Store или Microsoft Store. Если играете локально на RTX 50, установите GeForce Game Ready Driver версии **616.64 или новее**.
2. Откройте **настройки экрана** (Display Settings) и в пункте **Upscale Type** выберите **NVIDIA DLSS**.
3. Включите **Neural Rendering**. Если NVIDIA DLSS уже выбран, переключать нейрорендеринг можно сочетанием **Shift + Alt + B**.

Если переключатель отсутствует, проверьте версию игры, видеокарту и драйвер. Если после включения снизилась плавность, отключите Neural Rendering и сравните одну и ту же сцену при остальных неизменных настройках. Путь к переключателю и требования приводит [служба поддержки Portkey Games](https://portkeygamessupport.wbgames.com/hc/en-us/articles/56349775286419).

## На чём работает нейрорендеринг

| Устройство или сервис | Условия |
| --- | --- |
| ПК и ноутбуки с GeForce RTX 50 | Актуальная PC-версия игры и Game Ready 616.64 или новее |
| ПК на RTX Spark | Поддержку заявила NVIDIA |
| GeForce NOW | PC-версия через подписку Ultimate, расчёт идёт на сервере |
| GeForce RTX 20–40 и консоли | Для нейрорендеринга DLSS 5 в этой игре поддержка не заявлена |

## Что меняется в игре

Что именно делает DLSS 5: это не апскейл и не генерация кадров. Нейросеть работает последним этапом конвейера и дорисовывает то, что обычно вырезают ради производительности — свет, тени, материалы, отражения, — опираясь на кадр движка с его геометрией, текстурами и буферами освещения. Управлять этим можно точечно: разные модели для разных сцен, интенсивность и семантические маски, которые распознают объекты. Именно масками Avalanche Software и объясняла, почему в этот раз не тронуты лица.

![Персонажи Hogwarts Legacy после включения нейрорендеринга: лица и внешность остались прежними](/assets/img/hogwarts-legacy-dlss-5-foto.jpg)

Это важная деталь. DLSS 5 с момента анонса в марте получила свою порцию скандала именно из-за лиц: демонстрации выглядели так, будто нейросеть переизобретает персонажей. В Hogwarts Legacy изменения намеренно тише — в промо-кадрах заметно, что подтянулись свет и материалы, а не внешность. Хосе Виллета из Avalanche Software говорит, что команда вместе с NVIDIA настраивала окружение, тон и параметры кожи, «чтобы игра осталась верна исходному замыслу».

В своём тесте NVIDIA получила до 300 fps в 4K на RTX 5090 с трассировкой, Ray Reconstruction и 6× Multi Frame Generation. В результат входят сгенерированные кадры. В игре на другой системе частота кадров будет зависеть от настроек и железа.

Оценка: главное в этом обновлении не картинка, а то, что NVIDIA показала управляемый вариант технологии. Если DLSS 5 научится улучшать мир, не переписывая персонажей, споры о ней станут техническими, а не эстетическими. Пока проверять это придётся на одной игре из двух — выбор невелик.
