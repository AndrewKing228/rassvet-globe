#!/usr/bin/env python3
"""
Сборка текстур 3D-глобуса: цвет дня, рельеф с маской воды, огни городов и запасные облака.
Когда менять: другие источники, размеры уровней детализации, кодирование рельефа (его же читает шейдер в шаблоне).

Запуск (пакеты из requirements.lock рядом):
    python build_globe.py --src data/globe-src --out data/globe

Что получается в --out (имена с хешем содержимого, кэшируются браузером навсегда):
    color-<w>.<hash>.webp    NASA Blue Marble NG (топография и батиметрия, июль 2004), sRGB, w = 1024/2048/4096
    relief-<w>.<hash>.webp   без потерь: R, G — наклоны рельефа на восток и на север (GEBCO_2026),
                             B — доля воды в пикселе (Natural Earth: океан и озёра)
    night-<w>.<hash>.webp    яркость огней городов (NASA Black Marble 2016)
    clouds-<w>.<hash>.jpg    облака NASA Blue Marble — запасные, если ежедневные (updater) недоступны
    globe.json               манифест: файлы по уровням, цветовая подстройка ближних снимков, атрибуция

Кодирование наклона (должно совпадать с earthDecodeSlope в шаблоне):
    s = dh/dx (м/м), e = sign(s) * sqrt(min(|s|, SLOPE_MAX) / SLOPE_MAX), байт = round(127.5 + 127.5 * e)
Корень даёт точность на пологом рельефе: шаг у нуля ~0,00006, у SLOPE_MAX ~0,016.
"""
import argparse, datetime as dt, hashlib, io, json, logging, math, os, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.request, zipfile

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None          # исходники NASA больше лимита Pillow по умолчанию
log = logging.getLogger("globe")

UA = "rassvet-globe-build/1.0 (+https://github.com/AndrewKing228)"
SOURCES = {
    # ключ: (URL, имя файла в --src, размер в байтах на 2026-10-04 для проверки докачки; None — не проверять)
    "bmng": ("https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73751/world.topo.bathy.200407.3x21600x10800.jpg",
             "world.topo.bathy.200407.3x21600x10800.jpg", 27201049),
    "blackmarble": ("https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144898/BlackMarble_2016_3km.jpg",
                    "BlackMarble_2016_3km.jpg", 8106233),
    "gebco": ("https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/geotiff/gebco_2026_geotiff.zip?download=1",
              "gebco_2026_geotiff.zip", 4241629269),
    "ne_ocean": ("https://naciscdn.org/naturalearth/10m/physical/ne_10m_ocean.zip", "ne_10m_ocean.zip", None),
    "ne_lakes": ("https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip", "ne_10m_lakes.zip", None),
    "clouds": ("https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57747/cloud_combined_8192.tif",
               "cloud_combined_8192.tif", 35870468),
}
SIZES = (1024, 2048, 4096)             # ширина equirectangular-текстуры; высота = ширина / 2
DEM_WIDTH = 8192                       # сетка, на которую усредняется GEBCO перед расчётом наклонов
SLOPE_MAX = 1.0
EARTH_RADIUS = 6371008.8
# Ближние снимки для подстройки цвета ближнего вида (тот же источник, что у тайлов /tiles/img/)
EOX_TILE = os.environ.get("EOX_TILE_URL",
                          "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg")
ATTRIBUTION = [
    {"what": "day", "text": "NASA Earth Observatory, Blue Marble: Next Generation", "url": "https://science.nasa.gov/earth/earth-observatory/"},
    {"what": "night", "text": "NASA Earth Observatory, Black Marble 2016", "url": "https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/"},
    {"what": "relief", "text": "GEBCO Bathymetric Compilation Group 2026 (2026). The GEBCO_2026 Grid. doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa",
     "url": "https://doi.org/10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa"},
    {"what": "water", "text": "Made with Natural Earth", "url": "https://www.naturalearthdata.com/"},
]


# ---------------------------------------------------------------- загрузка

def download(key, src_dir):
    """Скачивает источник с докачкой; повторный запуск не качает заново."""
    url, name, size = SOURCES[key]
    path = os.path.join(src_dir, name)
    if os.path.exists(path) and (size is None or os.path.getsize(path) == size):
        return path
    part = path + ".part"
    if os.path.exists(path) and not os.path.exists(part):
        os.replace(path, part)                     # файл неполный — докачиваем его
    for attempt in range(1, 6):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"User-Agent": UA}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                mode = "ab" if (have and r.status == 206) else "wb"
                total = r.headers.get("Content-Length")
                log.info("  %s: %s (%s байт%s)", key, url, total, ", докачка" if mode == "ab" else "")
                with open(part, mode) as f:
                    shutil.copyfileobj(r, f, 1 << 20)
            if size is not None and os.path.getsize(part) != size:
                raise IOError(f"размер {os.path.getsize(part)} вместо {size}")
            os.replace(part, path)
            return path
        except (urllib.error.URLError, IOError, TimeoutError) as e:
            log.warning("  %s: попытка %d не удалась: %s", key, attempt, e)
            time.sleep(min(60, 5 * attempt))
    raise SystemExit(f"Не удалось скачать {url}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- кодирование

def save_webp(im, path, lossless=False, quality=90):
    """WebP через cwebp (есть -sharp_yuv: меньше мыла от цвета 4:2:0), иначе через Pillow."""
    cwebp = shutil.which("cwebp")
    if cwebp:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
            tmp = t.name
        try:
            im.save(tmp, "PNG", compress_level=1)
            args = [cwebp, "-quiet", "-metadata", "none", "-mt"]
            # рельеф: near_lossless (малая ошибка на канал, незаметна в светотени) — легче чистого lossless
            args += ["-near_lossless", "60", "-exact", "-z", "9"] if lossless else ["-q", str(quality), "-m", "6", "-sharp_yuv", "-af"]
            subprocess.run(args + [tmp, "-o", path], check=True)
        finally:
            os.unlink(tmp)
    elif lossless:
        im.save(path, "WEBP", lossless=True, exact=True, method=6, quality=100)
    else:
        im.save(path, "WEBP", quality=quality, method=6)


def publish(tmp_path, out_dir, stem, ext):
    """Переносит файл в --out под именем с хешем содержимого."""
    h = sha256(tmp_path)[:10]
    name = f"{stem}.{h}.{ext}"
    os.replace(tmp_path, os.path.join(out_dir, name))
    return name


def resize(im, w, resample=Image.LANCZOS):
    return im.resize((w, w // 2), resample, reducing_gap=3.0)


def block_mean(a, f):
    """Уменьшение в f раз усреднением блоков f×f (края по долготе не перекрываются, шва нет)."""
    h, w = a.shape[0] // f, a.shape[1] // f
    return a[:h * f, :w * f].reshape(h, f, w, f).mean(axis=(1, 3))


# ---------------------------------------------------------------- слои

def build_color(src, out_dir, work):
    im = Image.open(src)
    im.draft("RGB", (im.width // 2, im.height // 2))     # JPEG декодируется сразу в 10800×5400
    im = im.convert("RGB")
    names = {}
    for w in SIZES:
        tmp = os.path.join(work, f"color-{w}.webp")
        save_webp(resize(im, w), tmp, quality=90 if w >= 4096 else 88)
        names[w] = publish(tmp, out_dir, f"color-{w}", "webp")
        log.info("  цвет %d: %s, %d КБ", w, names[w], os.path.getsize(os.path.join(out_dir, names[w])) // 1024)
    return names, im


def read_gebco(zip_path, width):
    """GEBCO_2026 (8 тайлов 21600×21600) -> средние высоты на сетке width × width/2."""
    import rasterio
    from rasterio.enums import Resampling
    height = width // 2
    elev = np.full((height, width), np.nan, np.float32)
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith((".tif", ".tiff")))
    if not names:
        raise SystemExit("В архиве GEBCO нет GeoTIFF")
    for n in names:
        with rasterio.open(f"zip://{os.path.abspath(zip_path)}!/{n}") as ds:
            b = ds.bounds
            x0, x1 = round((b.left + 180) / 360 * width), round((b.right + 180) / 360 * width)
            y0, y1 = round((90 - b.top) / 180 * height), round((90 - b.bottom) / 180 * height)
            t0 = time.time()
            elev[y0:y1, x0:x1] = ds.read(1, out_shape=(y1 - y0, x1 - x0), resampling=Resampling.average).astype(np.float32)
            log.info("  GEBCO %s -> [%d:%d, %d:%d] за %.0f с", n, y0, y1, x0, x1, time.time() - t0)
    if np.isnan(elev).any():
        raise SystemExit(f"GEBCO покрыл не всю сетку: пустых пикселей {int(np.isnan(elev).sum())}")
    return elev


def water_mask(ocean_zip, lakes_zip, width):
    """Доля воды в пикселе: Natural Earth 10m (океан + озёра), растр в 2 раза плотнее с усреднением."""
    import shapefile
    from rasterio import features
    from rasterio.transform import from_bounds
    W, H = width * 2, width
    shapes = []
    for zp in (ocean_zip, lakes_zip):
        with zipfile.ZipFile(zp) as z:
            base = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
            with z.open(base + ".shp") as shp, z.open(base + ".dbf") as dbf, z.open(base + ".shx") as shx:
                r = shapefile.Reader(shp=io.BytesIO(shp.read()), dbf=io.BytesIO(dbf.read()), shx=io.BytesIO(shx.read()))
                shapes += [(s.__geo_interface__, 1) for s in r.shapes() if s.points]
    log.info("  Natural Earth: %d полигонов воды", len(shapes))
    m = features.rasterize(shapes, out_shape=(H, W), transform=from_bounds(-180, -90, 180, 90, W, H),
                           fill=0, dtype="uint8")
    return block_mean(m.astype(np.float32), 2)                      # width × width/2, 0..1


def slopes(elev):
    """Наклоны dh/dx (восток) и dh/dy (север) в м/м на сфере; по долготе — с переходом через 180°."""
    H, W = elev.shape
    lat = np.radians(90 - (np.arange(H) + 0.5) * 180 / H)
    dx = EARTH_RADIUS * np.maximum(np.cos(lat), 1e-3) * 2 * math.pi / W
    dy = EARTH_RADIUS * math.pi / H
    sx = (np.roll(elev, -1, axis=1) - np.roll(elev, 1, axis=1)) / (2 * dx[:, None])
    north = np.vstack([elev[:1], elev[:-1]])
    south = np.vstack([elev[1:], elev[-1:]])
    sy = (north - south) / (2 * dy)
    return sx, sy


def encode_slope(s):
    e = np.sign(s) * np.sqrt(np.minimum(np.abs(s), SLOPE_MAX) / SLOPE_MAX)
    return np.clip(np.round(127.5 + 127.5 * e), 0, 255).astype(np.uint8)


def build_relief(gebco_zip, ocean_zip, lakes_zip, out_dir, work):
    elev = read_gebco(gebco_zip, DEM_WIDTH)
    water_full = water_mask(ocean_zip, lakes_zip, DEM_WIDTH)
    elev = np.where(water_full > 0.5, np.maximum(elev, 0), elev)   # поверхность воды плоская (и у Каспия)
    names, masks = {}, {}
    for w in SIZES:
        f = DEM_WIDTH // w
        e = block_mean(elev, f) if f > 1 else elev
        water = block_mean(water_full, f) if f > 1 else water_full
        sx, sy = slopes(e)
        dry = 1 - np.clip(water, 0, 1)
        rgb = np.dstack([encode_slope(sx * dry), encode_slope(sy * dry), np.round(water * 255).astype(np.uint8)])
        tmp = os.path.join(work, f"relief-{w}.webp")
        save_webp(Image.fromarray(rgb, "RGB"), tmp, lossless=True)
        names[w] = publish(tmp, out_dir, f"relief-{w}", "webp")
        masks[w] = water
        log.info("  рельеф %d: %s, %d КБ, наклон p99 = %.3f", w, names[w],
                 os.path.getsize(os.path.join(out_dir, names[w])) // 1024, float(np.percentile(np.abs(sx), 99)))
    return names, masks


def build_night(src, out_dir, work):
    im = Image.open(src).convert("RGB")
    a = np.asarray(im, np.float32) / 255
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    # В Black Marble под огнями — тусклая голубоватая суша (яркость ≈ 0,55–0,65 синего канала), огни тёплые и белые
    # (яркость ≈ синему). Вычитание 0,68·B убирает сушу, лёд и океан, оставляя только свет городов, факелов и судов.
    lights = np.clip((lum - 0.68 * a[..., 2]) / 0.32, 0, 1)
    log.info("  Black Marble: огней в %.2f %% пикселей", float((lights > 0.05).mean() * 100))
    base = Image.fromarray(np.round(lights * 255).astype(np.uint8), "L")
    names = {}
    for w in SIZES:
        small = np.asarray(resize(base, w, Image.BOX), np.float32) / 255
        small = np.power(small, 0.8)              # при уменьшении огни тускнеют — немного вытягиваем
        tmp = os.path.join(work, f"night-{w}.webp")
        save_webp(Image.fromarray(np.round(small * 255).astype(np.uint8), "L").convert("RGB"), tmp, quality=85)
        names[w] = publish(tmp, out_dir, f"night-{w}", "webp")
    return names


def build_clouds(src, out_dir, work):
    im = Image.open(src).convert("L")
    names = {}
    for w in SIZES:
        tmp = os.path.join(work, f"clouds-{w}.jpg")
        resize(im, w).save(tmp, "JPEG", quality=85, optimize=True, progressive=True)
        names[w] = publish(tmp, out_dir, f"clouds-{w}", "jpg")
    return names


def near_color_match(color_im, water):
    """Подстройка цвета ближних снимков (Sentinel-2) под Blue Marble: усиление и сдвиг по каналам.
    Сравниваются средние и разбросы по суше между широтами ±60° на мозаике z3. Без сети — единичная."""
    ident = {"gain": [1, 1, 1], "bias": [0, 0, 0]}
    try:
        z, n = 3, 8
        mosaic = Image.new("RGB", (256 * n, 256 * n))
        for y in range(n):
            for x in range(n):
                req = urllib.request.Request(EOX_TILE.format(z=z, x=x, y=y), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    mosaic.paste(Image.open(io.BytesIO(r.read())).convert("RGB"), (256 * x, 256 * y))
        m = np.asarray(mosaic, np.float32) / 255
        rows = np.arange(m.shape[0])
        lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (rows + 0.5) / m.shape[0]))))
        w = water.shape[1]
        wy = np.clip(((90 - lat) / 180 * water.shape[0]).astype(int), 0, water.shape[0] - 1)
        wx = np.clip((np.arange(m.shape[1]) + 0.5) / m.shape[1] * w, 0, w - 1).astype(int)
        land_s2 = (water[wy][:, wx] < 0.1) & (np.abs(lat) < 60)[:, None]
        c = np.asarray(resize(color_im, w), np.float32) / 255
        clat = 90 - (np.arange(c.shape[0]) + 0.5) * 180 / c.shape[0]
        land_bm = (water < 0.1) & (np.abs(clat) < 60)[:, None]
        gain, bias = [], []
        for k in range(3):
            s, b = m[..., k][land_s2], c[..., k][land_bm]
            g = float(np.clip(b.std() / max(s.std(), 1e-3), 0.7, 1.4))
            gain.append(round(g, 4))
            bias.append(round(float(np.clip(b.mean() - g * s.mean(), -0.2, 0.2)), 4))
        log.info("  цвет Sentinel-2 -> Blue Marble: усиление %s, сдвиг %s", gain, bias)
        return {"gain": gain, "bias": bias}
    except Exception as e:  # сеть, формат — не критично
        log.warning("  подстройка цвета ближних снимков пропущена: %s", e)
        return ident


# ---------------------------------------------------------------- сборка

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="кэш исходников (около 4,5 ГБ)")
    ap.add_argument("--out", required=True, help="куда положить текстуры и globe.json")
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    os.makedirs(args.src, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    log.info("==> исходники")
    paths = {k: download(k, args.src) for k in SOURCES}
    if args.download_only:
        return 0
    manifest_src = {k: {"url": SOURCES[k][0], "sha256": sha256(p)} for k, p in paths.items() if k != "gebco"}
    manifest_src["gebco"] = {"url": SOURCES["gebco"][0], "bytes": os.path.getsize(paths["gebco"])}

    work = tempfile.mkdtemp(prefix=".build-", dir=args.out)
    try:
        log.info("==> цвет дня")
        color, color_im = build_color(paths["bmng"], args.out, work)
        log.info("==> рельеф и маска воды")
        relief, masks = build_relief(paths["gebco"], paths["ne_ocean"], paths["ne_lakes"], args.out, work)
        log.info("==> огни городов")
        night = build_night(paths["blackmarble"], args.out, work)
        log.info("==> запасные облака")
        clouds = build_clouds(paths["clouds"], args.out, work)
        log.info("==> цвет ближних снимков")
        near = near_color_match(color_im, masks[1024])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    manifest = {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "textures": {"color": color, "relief": relief, "night": night, "clouds": clouds},
        "slopeMax": SLOPE_MAX,
        "cloudLevels": [0.10, 0.80],      # пороги яркости запасных облаков NASA (живые — в sources.yml updater)
        "nearColor": near,
        "sources": manifest_src,
        "attribution": ATTRIBUTION,
    }
    old = os.path.join(args.out, "globe.json")
    keep = {n for t in manifest["textures"].values() for n in t.values()}
    if os.path.exists(old):           # файлы прежней версии оставляем: их могут догружать открытые вкладки
        try:
            with open(old, encoding="utf-8") as f:
                keep |= {n for t in json.load(f)["textures"].values() for n in t.values()}
        except (ValueError, KeyError) as e:
            log.warning("прежний globe.json не прочитан: %s", e)
    tmp = old + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    os.replace(tmp, old)
    for n in os.listdir(args.out):
        if n not in keep and n != "globe.json" and n.split(".")[0].split("-")[0] in ("color", "relief", "night", "clouds"):
            os.unlink(os.path.join(args.out, n))
    total = sum(os.path.getsize(os.path.join(args.out, n)) for n in keep if os.path.exists(os.path.join(args.out, n)))
    log.info("Готово: %s, %d файлов, %.1f МБ", old, len(keep), total / 1e6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
