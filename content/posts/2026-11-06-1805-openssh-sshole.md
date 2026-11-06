---
title: OpenSSH пускает в Alpine одним длинным паролем
date: 2026-11-06 18:05
category: gadgets
summary: В OpenSSH нашли дыру CVE-2026-123158: на musl-системах вроде Alpine любой пароль длиннее 256 символов открывает служебные аккаунты без пароля. Патч вышел 5 ноября, а через девять часов уязвимость уже пытались использовать вживую.
tldr: Уязвимы OpenSSH на musl-Linux (Alpine, OpenWrt, Buildroot, Yocto) без PAM — то есть конфигурация Alpine по умолчанию | Пароль на 257–1024 символа проходит как валидный для аккаунтов с «*» в /etc/shadow, включая root и пользователей «только по ключу» | Дыра живёт с 2016 года, патч — OpenSSH 10.6p2, Alpine закрыла 3.16–3.24 и edge; обновление требует перезапуска sshd
cover: /assets/img/openssh-sshole.jpg
pin: /assets/img/2026-11-06-1805-openssh-sshole-pin.jpg
credit: Обложка: GEEKOVSKI. Фото: Pexels / panumas nikhomkhai, Tima Miroshnichenko
sources: Ars Technica — Meet *sshole, the vulnerability that lets hackers SSH into Linux devices | https://arstechnica.com/security/2026/11/vulnerability-allows-attackers-to-log-into-some-linux-devices-sans-password/; BleepingComputer — OpenSSH flaw lets attackers log into password-disabled Linux accounts | https://www.bleepingcomputer.com/news/security/openssh-flaw-lets-attackers-log-into-password-disabled-linux-accounts/; SecurityWeek — OpenSSH Rushes Patches for 'SSHole' Authentication Bypass | https://www.securityweek.com/openssh-rushes-patches-for-sshole-authentication-bypass/; Help Net Security — OpenSSH flaw exploited in the wild just hours after disclosure | https://www.helpnetsecurity.com/2026/11/06/openssh-sshole-cve-2026-123158-exploitation/
---

5 ноября OpenSSH выпустил обновление 10.6p2, закрывающее дыру, которую исследователь Озгюн Кюльтекин из Wakefield нашёл и назвал *sshole. Уязвимости присвоен номер CVE-2026-123158 и оценка 8.1 по CVSS. Это не слух и не утечка: патч вышел официально, Alpine Linux в тот же день опубликовала собственный бюллетень и разослала исправленные пакеты. Суть проблемы — аутентификация, которую можно обойти, не зная ни одного пароля.

Затронуты Linux-системы на библиотеке musl, где OpenSSH собран без PAM и с включённой парольной аутентификацией. Это Alpine — в том числе её конфигурация по умолчанию, — а также OpenWrt, Buildroot и Yocto. Механика такая: служебные аккаунты, которым вход по паролю запрещён, держат в /etc/shadow звёздочку вместо хеша. В 2016 году OpenSSH специально научили считать хеш даже для таких аккаунтов — чтобы по времени ответа нельзя было вычислить существующие имена (CVE-2016-6210). Но musl-функция crypt() при ошибке тоже возвращает звёздочку, в том числе когда присланный пароль длиннее 256 байт. Дальше sshd сравнивает звёздочку со звёздочкой — и впускает.

То есть эксплойт — это пароль на 257–1024 символа. Нужны ещё два условия: хотя бы один обычный аккаунт с настоящим хешем SHA-256 или SHA-512 (у него sshd берёт соль) и открытый наружу SSH. Root сам по себе защищён настройкой PermitRootLogin по умолчанию, но косвенный путь есть: на официальных облачных образах Alpine для AWS и Azure (tiny-cloud с 3.18.11 по 3.24.3) пользователь alpine по умолчанию входит без пароля и имеет doas без пароля — то есть получает root.

Масштаб оценивают по косвенным числам. У образа Alpine в Docker Hub больше миллиарда скачиваний, сама система живёт в роутерах, телевизорах и промышленных контроллерах, которые обновляют годами, а то и никогда. По данным Detectify, в Shodan около 22 млн систем с открытым 22-м портом — подходят из них далеко не все, но проверка одного адреса занимает одну попытку.

Долго ждать эксплуатации не пришлось. Компания Previdian 6 ноября сообщила, что её датчики зафиксировали первую попытку меньше чем через девять часов после публикации CVE и подтвердили успешный вход под root на ханипоте с настоящими Alpine и OpenSSH. Атака шла с адреса 89.116.89[.]18, дальше — разведка командами id, uname и hostname в неинтерактивных сессиях; всего восемь попыток с одного адреса.

Что делать, если у вас musl-система без PAM: обновить openssh (в Alpine — apk upgrade openssh) и обязательно перезапустить sshd, потому что работающий процесс продолжает жить со старым кодом. Если обновиться нельзя — выключить вход по паролю через PasswordAuthentication no. Проверить, не входили ли к вам, можно по строкам «Accepted password» в /var/log/messages: логин аккаунта, у которого пароля нет, — повод считать машину скомпрометированной. Debian, Ubuntu и Fedora на glibc, конфигурации через PAM, Dropbear и OpenBSD проблеме не подвержены.

![Тёмный экран монитора с данными кибербезопасности и строками кода](/assets/img/openssh-sshole-foto.jpg)

Кто виноват — стороны спорят до сих пор. OpenSSH считает, что причина вне sshd, хотя эксплуатируется баг именно через него; автор musl Рич Фелкер настаивает, что это ошибка вызывающей стороны, а не библиотеки. Для администратора это уже неважно: дыра десять лет была в конфигурации по умолчанию у одного из самых популярных лёгких дистрибутивов, и это тот случай, когда «обновимся на следующей неделе» стоит дороже перезапуска sshd.
