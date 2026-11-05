---
title: FSR 4 на Xbox: машинный апскейл для разработчиков
date: 2026-11-05 09:05
category: xbox
summary: Microsoft открыла студиям FSR Upscaling 4 на Xbox Series X|S — нейросетевой апскейл добрался до консолей 2020 года. Полная модель на Series S стоит 5,2 мс кадра.
tldr: FSR Upscaling 4 доступен разработчикам Xbox Series X|S и портативок ROG Xbox Ally с 4 ноября | В сэмпле GDK две модели INT8 — Full и Lite, плюс переключение на старый FSR 3 | Дороже всего полная модель на Series S: 5,2 мс при выводе 1440p | Это инструмент для студий, а не обновление системы — играм нужны патчи
cover: /assets/img/fsr-4-xbox.jpg
pin: /assets/img/fsr-4-xbox-pin.jpg
credit: Обложка: Doop / GEEKOVSKI. Фото: Pexels (Nikolaos Kofidis), свободная лицензия.
sources: Microsoft Developer — AMD FSR Upscaling 4 Is Now Available for Xbox | https://developer.microsoft.com/en-us/games/articles/2026/11/amd-fsr-upscaling-4-is-now-available-for-xbox/; The Verge — Xbox developers can now put FSR 4 upscaling in their games | https://www.theverge.com/games/1027195/xbox-developers-can-now-put-fsr-4-upscaling-in-their-games; The Verge — AMD is bringing FSR 4.1 to Xbox consoles and handhelds | https://www.theverge.com/news/1014455/amd-fsr-4-1-xbox-consoles-handhelds-laptops; GitHub — Microsoft Xbox GDK Samples, AMD_FSR | https://github.com/microsoft/Xbox-GDK-Samples/tree/main/Samples/Graphics/AMD_FSR
---

4 ноября Microsoft объявила, что AMD FSR Upscaling 4 доступен разработчикам Xbox — на Series X|S и на портативках ASUS ROG Xbox Ally. Главный вопрос не «что включили», а «сколько это стоит по кадру».

![Консоль, геймпад и телевизор — та связка, где апскейл стал обязательным](/assets/img/fsr-4-xbox-tv.jpg)

## Что открыли

FSR Upscaling 4 работает на нейросетях в формате INT8. Консоли Series X|S вышли в 2020-м на GPU архитектуры RDNA 2, а FSR 4 писали под свежие Radeon, поэтому Microsoft с AMD отдельно оптимизировала код под консольные бюджеты вычислений — об этом пишет Клод Мараис, ведущий инженер команды Xbox.

В сэмпле GDK на GitHub две модели, Full и Lite, и переключение между FSR 4.1 Full, FSR 4.1 Lite и старым аналитическим FSR 3: студия может сравнить картинку и стоимость в своей сцене.

## Сколько это в миллисекундах

Это чистое время GPU на апскейл, без остального рендера:

- Series X: Lite — 1,29 мс в 1440p и 2,75 мс в 4K, Full — 1,95 мс и 3,86 мс.
- Series S: Lite — 1,9 мс в 1080p и 3,4 мс в 1440p, Full — 2,9 мс и 5,2 мс.

![Плата и чипы: апскейл — это дополнительные миллисекунды на GPU](/assets/img/fsr-4-xbox-chips.jpg)

5,2 мс на Series S — самая дорогая строчка. The Verge считает, что этого хватит, чтобы 60 fps просели примерно до 45: бюджет кадра при 60 fps — 16,6 мс, и полная модель съедает почти треть.

## Патчи — дело студий

Системного обновления не будет: Microsoft раздала инструмент, а список игр не публикует ни она, ни AMD. Каждая студия сама встраивает апскейл в движок и выпускает патч.

FSR 4.1 вышел в марте для Radeon RX 9000, в октябре AMD расширила его на RX 6000, ноутбуки и Xbox Ally, пообещав консоли «очень скоро». Поддержка заявлена более чем в 300 играх, включая Cyberpunk 2077, Battlefield 6 и Assassin's Creed Shadows.

## Оценка

Главный адресат — Series S. Апскейл даёт младшей консоли шанс держать разрешение вывода, не разваливая кадр, но Full за 5,2 мс там перестаёт быть опцией: Lite выглядит единственным здравым выбором. У Series X запас больше — 3,86 мс за 4K терпимо для 60 fps в большинстве проектов.

И главное: новость про Xbox 4 ноября, а не про ваш телевизор. Всё это пока живёт в сэмпле на GitHub, и от издателей, а не от Microsoft, зависит, когда разницу увидят игроки.
