# 📜 Изменения / Changelog

Здесь — что меняется на странице и в репозитории. Даты по UTC.
What changes on the page and in the repository. Dates are UTC.

## v1.5.2 — 2026-10-06

### Русский
- **Обновлённые 3D-модели видны сразу:** к адресу модели добавляется её версия, поэтому браузер не показывает старую
  копию из кэша.

### English
- **Updated 3D models show up right away:** the model address now carries its version, so browsers no longer show
  an old cached copy.

## v1.5.1 — 2026-10-06

### Русский
- **3D-модели без дыр:** радиаторы МКС были «кусками», а крылья батарей S4 и S6 почти пропадали — упрощение сетки
  съедало края панелей, собранных из отдельных ячеек. Теперь панели перед упрощением сшиваются. Пересобраны МКС,
  Terra, Swift, OCO-2, Hinode и MMS; модели стали легче — 4,7 МБ вместо 7,2.
- В описании МКС отмечено: пристыкованных кораблей в модели NASA нет, крылья батарей повёрнуты так, как их
  поставили авторы модели.

### English
- **3D models without holes:** the ISS radiators looked broken and the S4 and S6 solar wings nearly vanished — mesh
  simplification ate the edges of panels made of separate cells. Panels are now stitched before simplification. The ISS,
  Terra, Swift, OCO-2, Hinode and MMS were rebuilt; the models got lighter — 4.7 MB instead of 7.2.
- The ISS description notes that the NASA model has no docked spacecraft and its solar wings are posed as the model
  authors set them.

## v1.5.0 — 2026-10-05

### Русский
- **МКС из 53 частей:** модули, сегменты фермы, батареи, робототехника и внешние эксперименты — NICER, GEDI,
  ECOSTRESS, OCO-3, CALET, MAXI, ASIM и другие; выбранная часть подгружается подробнее.
- **Новые официальные модели NASA:** Terra, Swift, OCO-2, Hinode и MMS, тоже по частям.
- **Фильтры удобнее:** панель шире, страны и типы видны сразу, сверху — сводка включённых фильтров с крестиками.

### English
- **The ISS in 53 parts:** modules, truss segments, arrays, robotics and external experiments — NICER, GEDI,
  ECOSTRESS, OCO-3, CALET, MAXI, ASIM and more; the selected part loads in more detail.
- **New official NASA models:** Terra, Swift, OCO-2, Hinode and MMS, also in parts.
- **Easier filters:** a wider panel, all countries and types visible at once, a summary of active filters with
  remove buttons on top.

## v1.4.0 — 2026-10-05

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
- **Панель в три вкладки** — «Системы», «Фильтры», «Вид»; **навигация по стране и типу системы**, системы
  сгруппированы по странам, страна видна у системы и в карточке аппарата.
- **3D-модели по частям:** МКС из 24 частей (модель NASA IGOAL), Hubble с метками, схемы с типовыми частями;
  «Разобрать», выбор части, короткое описание со ссылками на NASA, ESA и Википедию.
- **iPhone:** глобус больше не «замирает» при вращении сразу после загрузки; щипок не масштабирует страницу.
- **Быстрее:** атлас шрифта подписей строится один раз и вдвое легче — со всеми системами на телефоне
  примерно 26 кадров/с вместо 18.

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
- **A panel with three tabs** — Systems, Filters, View; **browse by country and system type**, systems grouped
  by country, the country shown for each system and in the satellite card.
- **3D models in parts:** the ISS in 24 parts (NASA IGOAL model), Hubble with markers, schematics with generic
  parts; take apart, pick a part, read a short description with links to NASA, ESA and Wikipedia.
- **iPhone:** the globe no longer freezes when rotated right after loading; pinching no longer zooms the page.
- **Faster:** the label font atlas is built once and is half as heavy — about 26 fps with all systems on a phone
  instead of 18.
