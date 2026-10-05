# 📜 Изменения / Changelog

Здесь — что меняется на странице и в репозитории. Даты по UTC.
What changes on the page and in the repository. Dates are UTC.

## 2026-10-05

### Русский

**Первая открытая версия** — 3D-глобус и 2D-карта со спутниками в реальном времени, расчёт SGP4 в браузере,
снимок орбит в странице, свои копии библиотек, шрифтов и текстур, только ночная Земля.

В тот же день добавлено:
- **Скорость:** расчёт положений в фоновом потоке, слои без лишних пересборок, регионы и города
  подгружаются после первого кадра. На ПК — больше 100 кадров/с с 10 тысячами объектов.
- **Новые системы:** GPS, Galileo, BeiDou, QZSS, NavIC, станции (МКС и Китайская станция), научные
  спутники, OneWeb, Iridium. Состав — по каталогу SATCAT, описания — по сайтам операторов.
- **Фильтры** по типу орбиты, владельцу и году запуска.
- **«Откуда эти данные»** в карточке аппарата: источник и возраст элементов орбиты, дата проверки описания;
  военные аппараты помечены как классифицированные по GCAT, назначение официально не подтверждено.
- **Три ближайших пролёта** любого аппарата прямо в карточке, с файлом для календаря и напоминанием.
- **3D-модель аппарата:** у МКС и телескопа Hubble — официальные модели NASA, у остальных — схема по типу
  платформы с пометкой «схема».
- **«Как это работает»:** элементы орбиты, SGP4, наклонение, типы орбит, трасса, зона покрытия и когда
  спутник видно глазом — простыми словами.
- **Проверка каталога** `scripts/catalog/check_catalog.py`.
- **Скрипт обновления бережёт CelesTrak:** выгрузку моложе 2 часов берёт из сохранённой копии, каталог SATCAT
  запрашивает без повторов, а если CelesTrak не отвечает — сразу берёт сохранённые копии остальных групп.
- **Ссылка на исходный код** на странице и подпись: проект сделан для популяризации космоса.

### English

**First open version** — a 3D globe and a 2D map with satellites in real time, SGP4 computed in the browser,
an orbit snapshot embedded in the page, self-hosted libraries, fonts and textures, night Earth only.

Added the same day:
- **Speed:** positions computed in a background thread, layers without needless rebuilds, regions and cities
  loaded after the first frame. Over 100 fps on a desktop with 10,000 objects.
- **New systems:** GPS, Galileo, BeiDou, QZSS, NavIC, stations (the ISS and the China Space Station), science
  satellites, OneWeb, Iridium. Line-up from the SATCAT catalogue, descriptions from operators' websites.
- **Filters** by orbit type, owner and launch year.
- **"Where this data comes from"** in the satellite card: source and age of the orbital elements, when the
  description was checked; military satellites are flagged as classified by GCAT, purpose not officially confirmed.
- **The next three passes** of any satellite right in its card, with a calendar file and a reminder.
- **3D model of the satellite:** official NASA models for the ISS and the Hubble telescope, a schematic by
  platform type labelled "schematic" for the rest.
- **"How it works":** orbital elements, SGP4, inclination, orbit types, the ground track, the coverage zone and
  when a satellite is visible to the eye — in plain words.
- **Catalogue check** `scripts/catalog/check_catalog.py`.
- **The update script spares CelesTrak:** a download younger than 2 hours is taken from the saved copy, the SATCAT
  catalogue is requested without retries, and if CelesTrak does not answer the remaining groups come from saved copies.
- **A link to the source code** on the page and a note: the project is made to popularise space.
