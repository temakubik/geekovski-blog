---
title: Steam Frame: стрим стал чётче, суперсэмплинг убрали
date: 2026-11-04 18:06
category: vr
summary: Valve выпустила бету SteamVR 2.19.1 с более резкой картинкой стрима на всех шлемах со Steam Link, а в SteamOS 0.5.7 для Steam Frame молча убрала Advanced Supersampling.
tldr: SteamVR 2.19.1 beta поднимает рендер по умолчанию до 1,5× с целью 1,4× разрешения панели | SteamOS 0.5.7 beta для Steam Frame убрала Advanced Supersampling без объяснений | Улучшения касаются Quest, Vive Focus, PICO и самого Frame
cover: /assets/img/steam-frame-steamvr-2-19-1.jpg
pin: /assets/img/steam-frame-steamvr-2-19-1-pin.jpg
credit: Обложка: Doop / GEEKOVSKI. Фото: Pexels (SHVETS production), свободная лицензия.
sources: Valve — SteamVR Beta 2.19.1, список изменений | https://store.steampowered.com/news/app/250820/view/683017363938871519; Road to VR — SteamVR Update Improves Image Quality for All Steam Link Compatible Headsets | https://roadtovr.com/steamvr-beta-update-image-quality-quest-frame-pico/; GamingOnLinux — SteamOS 0.5.7 Beta for Steam Frame | https://www.gamingonlinux.com/2026/11/steamos-0-5-7-beta-for-steam-frame-brings-webxr-improved-settings-and-more/; PCZ — Steam Frame climbs into the top five VR headsets in Valve's October Steam survey | https://www.pczone.co.uk/steam-frame-top-five-vr-headsets-steam-survey-october/
---

Valve выкатила в бета-каналы SteamVR 2.19.1 и SteamOS 0.5.7 для Steam Frame. Главное в обоих обновлениях — картинка при стриме PC VR по Wi-Fi: она стала резче. Но у самого шлема при этом убрали Advanced Supersampling, и причину Valve не объяснила.

## Что стало лучше

По списку изменений Steam Link теперь по умолчанию нацеливается на 1,4× разрешения панели: render scale 1,5, а GPU-тест для выбора разрешения больше не запускается. Размер кодируемого кадра на Steam Frame вырос с 1152 до 1216.

Ещё в Valve переписали пайплайн системного слоя: фовеальные и нефовеальные виды рендерятся прямо из исходных текстур, без промежуточной текстуры и лишнего ресемплинга. Плюс более качественный фильтр при даунсемпле цвета и более резкая периферия.

![Крупный план: шлем виртуальной реальности и контроллер в неоновом свете](/assets/img/steam-frame-steamvr-2-19-1-headset.jpg)

Касается это не только Frame: Steam Link — приложение SteamVR для стрима по Wi-Fi на Meta Quest, HTC Vive Focus и PICO; в списке также интерфейс SteamVR, стрим десктопа, оверлеи и театральный экран.

Сравнить «было/стало» можно вручную: Steam Link → Advanced → Stream Quality, Default или Legacy. Если раньше крутили разрешение или размер видео руками, для новых дефолтов верните Auto.

## Чего не стало

В SteamOS 0.5.7 beta для Steam Frame одна строка идёт без комментариев: поддержка Advanced Supersampling удалена. Это была одна из немногих ручек, которыми владелец выжимал резкость сверх дефолта, — и чем заменили, Valve не сказала.

Остальное обновление про починку: исправлена фильтрация вибрации в предсказании позы, звук больше не отваливается у USB- и Bluetooth-колонок, когда приложение берёт микрофон, батарея контроллеров Frame корректно показывает 0%, включён WebXR в Chromium 157.

В трекере SteamVR-for-Linux по 2.19.1 есть отчёт о рассинхроне при фовеальном стриме, если приложение не держит частоту: область высокого деталя идёт за взглядом на кадр позже. Обход — лок на кратную частоту или откат на стабильную 2.18.4.

## Контекст

Steam Frame вышел 14 сентября за $1 059 (256 ГБ) и $1 299 (1 ТБ). В октябрьском опросе Steam, первом полном месяце продаж, шлем сразу попал в топ-5 с 5,61%, обогнав Pico 4; правда, опрос опт-ин и про продажи не говорит.

![Человек в шлеме с контроллерами в тёмной комнате с неоновой подсветкой](/assets/img/steam-frame-steamvr-2-19-1-vr.jpg)

## Оценка

Поднять дефолтный рендер до 1,4× разрешения панели — красивый ход, но платят за него те, кто играет по среднему Wi-Fi и на старом GPU: 2.19.1 больше не меряет железо перед выбором разрешения, а просто ставит высокую планку. Toggle Legacy спасает, но найдут его не все.

Убрать Advanced Supersampling без объяснений — второе сомнительное решение за один апдейт. Шлем за тысячу с лишним долларов берут в том числе за возможность крутить картинку под себя. Похоже, Valve доводит стриминговую часть Frame до состояния «включил и работает» и вычищает то, что в эту картину не влезает.
