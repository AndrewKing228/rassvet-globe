# Third-party notices / Сторонние компоненты

Код и документация этого проекта распространяются по лицензии MIT (см. [LICENSE](LICENSE)).
Ниже перечислены сторонние библиотеки, шрифты, изображения и данные, которые лежат в репозитории
или вшиты в страницу, с их версиями, лицензиями и атрибуцией.

The project's own code and documentation are MIT-licensed (see [LICENSE](LICENSE)). Below are the
third-party libraries, fonts, imagery and data shipped in this repository or embedded in the page,
with their versions, licenses and attribution.

## Библиотеки / Libraries (`vendor/`)

| Компонент / Component | Версия / Version | Лицензия / License | Путь / Path | SHA-256 |
|---|---|---|---|---|
| [deck.gl](https://github.com/visgl/deck.gl) (`dist.min.js`, standalone bundle) | 9.4.0 | MIT, © vis.gl contributors | `vendor/deck.gl@9.4.0/dist.min.js`, [LICENSE](vendor/deck.gl@9.4.0/LICENSE) | `2eb6a1ae0d58604b1378682cd1136f8793478ba801e43dae48b3807e48758a6b` |
| [satellite.js](https://github.com/shashwatak/satellite-js) | 6.0.2 | MIT, © 2013 Shashwat Kandadai, UCSC | `vendor/satellite.js@6.0.2/satellite.min.js`, [LICENSE.md](vendor/satellite.js@6.0.2/LICENSE.md) | `14488fc910920924e6616f07f950ba307586e08fbb837407d8fe04c939b2059f` |
| [topojson-client](https://github.com/topojson/topojson-client) | 3.1.0 | ISC, © 2012–2019 Michael Bostock | `vendor/topojson-client@3.1.0/topojson-client.min.js`, [LICENSE](vendor/topojson-client@3.1.0/LICENSE) | `25cd02ae486cc5063e0215a4e4cfb15de83700c87ac48bac4d57dc6aaf3ebb89` |

Файлы взяты без изменений из npm-пакетов той же версии (`deck.gl/dist.min.js`,
`satellite.js/dist/satellite.min.js`, `topojson-client/dist/topojson-client.min.js`).
Files are unmodified copies from the npm packages of the same version.

Сборка deck.gl включает модули других авторов. Кроме пакетов vis.gl (luma.gl, loaders.gl, math.gl,
probe.gl, mjolnir.js — MIT), в ней есть код под другими разрешительными лицензиями; тексты лицензий
лежат рядом с файлом:

The deck.gl bundle includes modules by other authors. Besides vis.gl packages (luma.gl, loaders.gl,
math.gl, probe.gl, mjolnir.js — MIT), it contains code under other permissive licenses; their texts
are shipped next to the bundle:

| Модуль / Module | Лицензия / License | Текст / Text |
|---|---|---|
| [h3-js](https://github.com/uber/h3-js), © Uber Technologies | Apache-2.0 | [LICENSE.h3-js](vendor/deck.gl@9.4.0/LICENSE.h3-js) |
| [long.js](https://github.com/dcodeIO/long.js), © Daniel Wirtz, The Closure Library Authors | Apache-2.0 | [LICENSE.long](vendor/deck.gl@9.4.0/LICENSE.long) |
| [d3-hexbin](https://github.com/d3/d3-hexbin), © Mike Bostock | BSD-3-Clause | [LICENSE.d3-hexbin](vendor/deck.gl@9.4.0/LICENSE.d3-hexbin) |

## Шрифты / Fonts (`vendor/fonts-5.3.0/`)

| Шрифт / Font | Версия пакета / Package | Лицензия / License | Текст / Text |
|---|---|---|---|
| [Golos Text](https://github.com/googlefonts/golos-text), © 2019 The Golos Text Project Authors | [@fontsource/golos-text](https://fontsource.org/fonts/golos-text) 5.3.0 | SIL OFL 1.1 | [OFL-golos-text.txt](vendor/fonts-5.3.0/OFL-golos-text.txt) |
| [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono), © 2020 The JetBrains Mono Project Authors | [@fontsource/jetbrains-mono](https://fontsource.org/fonts/jetbrains-mono) 5.3.0 | SIL OFL 1.1 | [OFL-jetbrains-mono.txt](vendor/fonts-5.3.0/OFL-jetbrains-mono.txt) |

В `vendor/fonts-5.3.0/files/` лежат файлы `.woff2` из npm-архивов Fontsource без изменений;
`fonts.css` собран из CSS этих пакетов (оставлены только нужные начертания и формат woff2).
SHA-256 архивов: golos-text `7cb2c7e7937dabca661af46083f2297649be8abf9a268464096c1e3f512ccc57`,
jetbrains-mono `1bbea47d1387406da5b6ccc4184cc61eae6851cc0db5c1d9bbd088ea9daa0b4a`.

The `.woff2` files are unmodified copies from the Fontsource npm archives; `fonts.css` is assembled
from those packages' CSS (only the weights in use, woff2 only).

## Изображения Земли / Earth imagery

| Файлы / Files | Источник / Source | Лицензия / License | Атрибуция / Attribution |
|---|---|---|---|
| `globe/color-*.webp`, `earth-day.jpg` | [NASA Blue Marble: Next Generation](https://science.nasa.gov/earth/earth-observatory/) (топография и батиметрия, июль 2004) | NASA imagery, public domain | NASA Earth Observatory |
| `globe/night-*.webp`, `earth-night.jpg` | [NASA Black Marble 2016](https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/) | NASA imagery, public domain | NASA Earth Observatory |
| `globe/clouds-*.jpg` | NASA Blue Marble clouds (`cloud_combined_8192.tif`) | NASA imagery, public domain | NASA Earth Observatory |
| `globe/relief-*.webp` (каналы R, G — наклоны рельефа) | [GEBCO_2026 Grid](https://doi.org/10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa) | public domain, attribution requested | GEBCO Bathymetric Compilation Group 2026 (2026). The GEBCO_2026 Grid. doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa |
| `globe/relief-*.webp` (канал B — маска воды) | [Natural Earth](https://www.naturalearthdata.com/) 10m ocean, lakes | public domain | Made with Natural Earth |

Текстуры `globe/` собраны скриптом `scripts/globe/build_globe.py` (уменьшение, перекодирование в
WebP, расчёт наклонов); адреса и SHA-256 исходников записаны в `globe/globe.json`.
NASA не одобряет и не поддерживает этот проект.

The `globe/` textures were produced by `scripts/globe/build_globe.py` (downscaling, WebP encoding,
slope computation); source URLs and SHA-256 are recorded in `globe/globe.json`. NASA does not endorse
this project.

## 3D-модели / 3D models (`models/`)

| Файл / File | Источник / Source | SHA-256 исходника / of the original | SHA-256 файла / of the file | Лицензия / License | Атрибуция / Attribution |
|---|---|---|---|---|---|
| `models/iss.glb` | [NASA 3D Resources — International Space Station (ISS) (D) (IGOAL)](https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20(ISS)%20(D)%20(IGOAL)), `International Space Station (ISS).glb` | `57cecfaf332efb2127d07796c4b65ca570d95a11516c8e046feb5a12efee491d` | `9d497fbee84d357425c2c14367a728c77ba673ae239f93f51243411f859c1a43` | [NASA Images and Media Usage Guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/): работа правительства США, в США не охраняется авторским правом / US Government work, not subject to copyright in the US | NASA |
| `models/hubble.glb` | [NASA 3D Resources — Hubble Space Telescope (A)](https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/Hubble%20Space%20Telescope%20(A)), `Hubble_Space_Telescope__A_.glb` | `e5ba4de15c7d359ac8fa1ab7e286aff42dec09c0fadae3db99252587f39fa384` | `0b0ef5a20ac6a852edee2223121884da1bceb0a0ecd7b22cabc3c3e29766e491` | то же / same | NASA |

Изменения: модель МКС разделена на 24 части по узлам исходника, мелкие детали (поручни, разъёмы, наклейки)
и текстуры убраны, части окрашены однотонно, нормали убраны, сетка упрощена с 2,7 млн до 45 510
треугольников, применено квантование (скрипт `scripts/models/build-iss-parts.mjs`); у Hubble текстуры
уменьшены до 1024 px и пересжаты в WebP, применено квантование. Инструмент —
[gltf-transform](https://gltf-transform.dev/) 4.5.1 (MIT), команды — в README, раздел про
`scripts/models/`. Исходники скачаны 2026-10-05. Описания частей написаны по страницам NASA и ESA,
ссылки — в реестре и в окне модели.
NASA не одобряет и не поддерживает этот проект; модели не означают участия или поддержки NASA.

Changes: the ISS model was split into 24 parts along the original's nodes, small details (handrails,
connectors, decals) and textures removed, flat colours applied, normals removed, the mesh simplified
from 2.7 million to 45,510 triangles and quantised (`scripts/models/build-iss-parts.mjs`); the Hubble
model had its textures reduced to 1024 px and re-encoded as WebP and was quantised. Tool: gltf-transform
4.5.1 (MIT); the commands are in the README section on `scripts/models/`. Originals downloaded on
2026-10-05. Part descriptions are based on NASA and ESA pages, linked in the registry and the viewer.
NASA does not endorse this project; the models do not imply NASA participation or endorsement.

## Данные / Data

| Данные / Data | Где / Where | Лицензия / License | Атрибуция / Attribution |
|---|---|---|---|
| Границы стран, регионов, береговая линия, города | вшиты в `index.html` (блок `geo-data`) | [Natural Earth](https://www.naturalearthdata.com/), public domain | Made with Natural Earth |
| Элементы орбит (TLE / OMM), SATCAT | вшиты в `index.html` (блоки `data-*`) | [CelesTrak](https://celestrak.org/), публичные данные | Orbital data: CelesTrak (T.S. Kelso) |
| Классификация аппаратов (GCAT) | вшита в `index.html` | [GCAT](https://planet4589.org/space/gcat/), CC BY 4.0 | Jonathan C. McDowell, General Catalog of Artificial Space Objects |
| Сведения о группировке «Рассвет» (пуски, поколения, статусы) | вшиты в `index.html` (блок `data-rassvet`) | факты из открытых источников, ссылки на каждый источник — в самом блоке и в карточке аппарата | — |
| Состав GPS, Galileo, BeiDou, QZSS, NavIC, станций, научных спутников, OneWeb, Iridium | вшит в `index.html` (блоки `data-gps` … `data-iridium`), обновляется ежедневно | [CelesTrak SATCAT](https://celestrak.org/satcat/search.php), группы `gps-ops`, `galileo`, `beidou`, `gnss`, `stations`, `science`, `oneweb`, `iridium-NEXT` | Satellite catalog: CelesTrak SATCAT |
| Описания этих систем (оператор, назначение, орбиты) | реестр систем в `index.html` | официальные сайты операторов — GPS.gov, NAVCEN, EUSPA, BeiDou, QZSS (Cabinet Office, Japan), ISRO, NASA, CMSE, Eutelsat, Iridium; ссылки в карточке аппарата | факты со ссылками на источник |
| Элементы орбит Space-Track (только если скрипт обновления запущен с учётной записью) | блоки `data-*` | [Space-Track.org](https://www.space-track.org/documentation#/user_agree): общее разрешение USSPACECOM на распространение TLE/OMM/SATCAT с указанием источника | USSPACECOM via Space-Track.org — показывается в подвале страницы, когда данные получены оттуда |

Атрибуция всех источников также показывается в подвале страницы.
Attribution for all sources is also shown in the page footer.

## Источники, которые страница может использовать, но которых нет в репозитории

Sources the page can use but which are not shipped in this repository:

- Ближний вид глобуса с рельефом обращается к адресам `tiles/dem/…`, `tiles/img/…`, `tiles/night/…`
  того же сайта. В репозитории этих тайлов нет; без них глобус показывает общие текстуры из `globe/`.
  Ссылки на возможные источники в подвале страницы (EOxCloudless — CC BY-NC-SA 4.0,
  AWS Terrain Tiles, NASA GIBS) относятся только к этому режиму.
  The close-up terrain view requests `tiles/dem/…`, `tiles/img/…`, `tiles/night/…` on the same site.
  Those tiles are not in the repository; without them the globe uses the textures from `globe/`.
- Ежедневная карта облаков [Live Cloud Maps](https://github.com/matteason/live-cloud-maps)
  (CC0, contains modified EUMETSAT data) скачивается скриптом обновления в `clouds/`, только если он
  запущен с секцией `clouds` в `updater/sources.yml`.
  The daily cloud map is downloaded into `clouds/` only when the update script runs with the `clouds`
  section in `updater/sources.yml`.

## Инструменты разработки / Development tools

| Инструмент / Tool | Версия / Version | Лицензия / License | Где / Where |
|---|---|---|---|
| [gltf-transform](https://github.com/donmccurdy/glTF-Transform) (`@gltf-transform/cli`) | 4.5.1 | MIT, © Don McCurdy | `scripts/models/package.json`; сам пакет в репозитории не лежит / the package itself is not shipped |

## Python-пакеты для скриптов / Python packages for the scripts

Не входят в репозиторий, ставятся по `requirements.lock` (точные версии и хеши).
Not shipped; installed from `requirements.lock` (exact versions and hashes).

| Скрипт / Script | Пакеты / Packages |
|---|---|
| `updater/update.py` | sgp4 2.27 (MIT), PyYAML 6.0.3 (MIT) |
| `scripts/globe/build_globe.py` | numpy 2.4.6 (BSD-3-Clause), Pillow 12.3.0 (MIT-CMU), rasterio 1.4.4 (BSD-3-Clause), pyshp 3.1.6 (MIT) и их зависимости |
