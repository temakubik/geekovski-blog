---
slug: studio
name: Студия
kind: location
anchor: "a warm shared editorial studio: wooden shelves stacked with retro game consoles, cartridges and controllers, cardboard boxes and courier parcels with packing tape, coiled cables, plants, mugs, a laptop on a desk, warm tungsten lamp light and a string of warm lights"
mascot: "a fluffy white cat with amber eyes and thin round glasses, sitting on the shelf among the consoles"
style: "editorial 35mm film photograph, warm tungsten and afternoon window light, muted warm palette, subtle film grain, shallow depth of field, lived-in cozy room"
negative: "no text, no letters, no readable screens or posters, no logos, no watermarks, no illustration, no 3d render, no cold blue light, no sterile showroom look"
shots:
  - id: studio
    ratio: "3:2"
    scene: "the shelves and the floor in one frame: consoles and cartridges in neat stacks, parcels and boxes piled on the floor, coiled cables, a plant, mugs, a laptop half in frame, the white cat sitting on the middle shelf looking at the camera"
  - id: wide
    ratio: "3:2"
    scene: "wide view of the room with two facing desks and laptops, a wall of wooden shelves with consoles and film posters turned away, parcels on the floor, a guitar in the corner, big window with warm afternoon light"
  - id: cat
    ratio: "1:1"
    scene: "portrait of the mascot: the fluffy white cat with amber eyes and thin round glasses sitting on a shelf, one paw on a stack of game cartridges, retro console and parcels blurred behind"
---

# Студия и кот

Общая редакционная студия — место, где снимаются все «живые» кадры: сюда приходят Сева, Марк и Аня, здесь лежат коробки от посылок с техникой, на полках стоят старые консоли, а на средней полке сидит **кот** — белый, пушистый и в очках. Это символ студии и канала.

## Правила студии

- **Тёплая и дружелюбная, а не «тёмное логово гика».** Тёплый свет ламп и строки гирлянды, растения, плед на стуле, кружки. Хлам есть, но он аккуратный: стопки коробок, свёрнутые кабели, коробки от посылок — а не мусор.
- **Свет — тёплый.** Не холодный синий мониторный и не неон: студия должна читаться как «сюда приятно зайти».
- **Кот всегда может быть в кадре.** Он не в каждой картинке, но его присутствие — подпись студии. Очки на нём — часть образа, не менять.
- **Никакого текста в кадре.** Ни на коробках, ни на постерах, ни на экранах: подписи ставит шаблон.

## Готовые кадры

| Кадр | Файл | Источник |
|---|---|---|
| Полки, посылки и кот (3:2) | `img/studio/studio.jpg` | https://doop.design/a/BgdcWWJ-Lc.webp |
| Студия целиком (3:2) | `img/studio/wide.jpg` | https://doop.design/a/DEUJf0qPld.webp |
| Кот-символ в очках (1:1) | `img/studio/cat.jpg` | https://doop.design/a/yTtQlA62OO.webp |

## Промпт-формула для сцены

`{сцена из паспорта персонажа} + Studio: {anchor} + Style: {style} + Avoid: {negative}`

Для кадров с котом добавлять в сцену: `the white cat {mascot without "sitting on the shelf" part}` — иначе кот окажется не там, где нужно.
