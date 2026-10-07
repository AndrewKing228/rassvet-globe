#!/usr/bin/env python3
"""
Updater: раз в сутки скачивает орбитальные данные, проверяет их и публикует обновлённую страницу трекера.
Когда менять: логика загрузки, проверки или сборки страницы. Источники — в sources.yml.

Свежие элементы орбит -> валидация -> сборка HTML из шаблона -> атомарная публикация.

Режимы:
    update.py --once      одно обновление и выход
    update.py --loop      постоянная работа: догоняет пропуск при старте, дальше раз в сутки в UPDATE_HOUR_UTC
    update.py --dry-run   всё, кроме публикации: результат пишется в <data>/state/dry-run/index.html

Шаблон не меняется. В копии подменяется только содержимое data-блоков:
  <script type="text/plain" id="data-...">        3LE из источников, у которых этот id указан в blocks
  <script type="application/json" id="data-...">  элементы орбит существующих аппаратов по NORAD
                                                  (форматы constellation и catalog настоящего трекера)
плюс дата обновления (data-meta.generatedAt и/или <time id="last-updated">) и недостающие SEO/OG-теги в <head>.
"""
import argparse, datetime as dt, email.utils, gzip, hashlib, html, http.cookiejar, io, json, logging, logging.handlers, math, os, re
import signal, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

import yaml
from sgp4 import omm as sgp4_omm
from sgp4.api import Satrec, jday

try:
    import fcntl
except ImportError:  # локальный dry-run на Windows
    fcntl = None

log = logging.getLogger("updater")
UTC = dt.timezone.utc
MAX_DOWNLOAD = 128 * 1024 * 1024
BAD_FORMAT_SHARE = 0.05      # больше 5 % битых записей — считаем выгрузку повреждённой и не используем
# CelesTrak обновляет выгрузки примерно раз в 2 часа и на повторный запрос раньше отвечает 403, а за частые повторы
# может заблокировать адрес. Выгрузку моложе этого срока берём из кэша и источник не запрашиваем (повторный deploy).
REUSE_SECONDS = 2 * 3600
OMM_KEYS = ["EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
            "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT"]
SEO_DESCRIPTION = ("Карта и 3D-глобус спутников в реальном времени: российская группировка «Рассвет», "
                   "ГЛОНАСС, Starlink и другие системы. Элементы орбит обновляются ежедневно.")


class Stop(Exception):
    pass


# ---------- конфигурация ----------

def env_int(name, default):
    v = os.environ.get(name, "").strip()
    return int(v) if v else default


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    ids = [s["id"] for s in cfg["sources"]]
    if len(ids) != len(set(ids)):
        raise SystemExit("sources.yml: повторяющиеся id источников")
    for s in cfg["sources"]:
        if s.get("provider") not in ("celestrak", "spacetrack") or s.get("format") not in ("tle", "omm"):
            raise SystemExit(f"sources.yml: у {s['id']} неверный provider/format")
        if not re.fullmatch(r"[a-z0-9-]+", s["id"]):
            raise SystemExit(f"sources.yml: id {s['id']!r} — только a-z, 0-9 и дефис")
    return cfg


def setup_logging(data_dir):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(fmt)
    log.addHandler(out)
    logs = os.path.join(data_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(os.path.join(logs, "updater.log"), maxBytes=1_000_000,
                                              backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)


# ---------- загрузка ----------

def http_get(url, http_cfg, ua, data=None, opener=None, raw=False):
    """GET/POST с таймаутом и повторами. 4xx (кроме 408/429) не повторяем — это не временная ошибка.
    raw=True — вернуть байты (картинки), иначе текст."""
    retries, backoff = int(http_cfg.get("retries", 3)), float(http_cfg.get("backoff_seconds", 5))
    opener = opener or urllib.request.build_opener()
    last = None
    for attempt in range(retries + 1):
        if attempt:
            pause = backoff * 3 ** (attempt - 1)
            log.info("  повтор %d/%d через %.0f с", attempt, retries, pause)
            time.sleep(pause)
        req = urllib.request.Request(url, data=data, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
        try:
            with opener.open(req, timeout=float(http_cfg.get("timeout_seconds", 60))) as r:
                body = r.read(MAX_DOWNLOAD + 1)
                if len(body) > MAX_DOWNLOAD:
                    raise ValueError("ответ больше лимита")
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body if raw else body.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except Exception as e:  # сеть, таймаут, TLS, gzip
            last = f"{type(e).__name__}: {e}"
        log.warning("  %s: %s", url.split("?")[0], last)
    raise RuntimeError(last or "неизвестная ошибка")


def fetch_source(src, http_cfg, ua):
    """Вернуть (текст, url) или None, если источник пропускается (нет кредов Space-Track)."""
    fmt = {"tle": "tle", "omm": "json"}[src["format"]]
    if src["provider"] == "celestrak":
        url = "https://celestrak.org/NORAD/elements/gp.php?" + urllib.parse.urlencode({**src["params"], "FORMAT": fmt})
        return http_get(url, http_cfg, ua), url
    user, pw = os.environ.get("SPACETRACK_USER", ""), os.environ.get("SPACETRACK_PASS", "")
    if not (user and pw):
        return None
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    http_get("https://www.space-track.org/ajaxauth/login", http_cfg, ua, opener=opener,
             data=urllib.parse.urlencode({"identity": user, "password": pw}).encode())
    url = "https://www.space-track.org/basicspacedata/query/" + src["query"].lstrip("/")
    return http_get(url, http_cfg, ua, opener=opener), url


# ---------- разбор и валидация ----------

def alpha5(s):
    s = s.strip()
    if s and s[0].isalpha():
        return (ord(s[0].upper()) - 55 - (s[0].upper() > "I") - (s[0].upper() > "O")) * 10000 + int(s[1:])
    return int(s)


def tle_checksum_ok(line):
    if len(line) != 69 or not line[68].isdigit():
        return False
    return sum(int(c) if c.isdigit() else c == "-" for c in line[:68]) % 10 == int(line[68])


def jd_to_dt(jd, fr):
    return dt.datetime.fromtimestamp((jd - 2440587.5 + fr) * 86400.0, UTC)


def sat_ok(sat, now):
    """SGP4 считается без ошибок в эпоху и сейчас, положение физически осмысленно."""
    for jd, fr in ((sat.jdsatepoch, sat.jdsatepochF), jday(now.year, now.month, now.day, now.hour, now.minute, now.second)):
        err, r, _ = sat.sgp4(jd, fr)
        if err or not all(math.isfinite(x) for x in r) or math.hypot(*r) < 6300:
            return False
    return True


def parse_tle(text):
    recs, bad = [], 0
    lines = [l.rstrip() for l in text.splitlines()]
    for i, l1 in enumerate(lines):
        if not (l1.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 ")):
            continue
        l2 = lines[i + 1]
        name = lines[i - 1].strip() if i > 0 and not lines[i - 1].startswith(("1 ", "2 ")) else ""
        if name.startswith("0 "):
            name = name[2:].strip()
        try:
            if not (tle_checksum_ok(l1) and tle_checksum_ok(l2)) or l1[2:7] != l2[2:7]:
                raise ValueError("checksum")
            sat = Satrec.twoline2rv(l1, l2)
            recs.append(dict(norad=alpha5(l1[2:7]), name=name, kind="T", l1=l1, l2=l2, sat=sat,
                             epoch=jd_to_dt(sat.jdsatepoch, sat.jdsatepochF)))
        except Exception:
            bad += 1
    return recs, bad


def parse_omm(text):
    recs, bad = [], 0
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("OMM: ожидался JSON-массив")
    for o in data:
        try:
            ep = str(o["EPOCH"]).rstrip("Z")
            if "." not in ep:
                ep += ".0"
            fields = {"CLASSIFICATION_TYPE": "U", "EPHEMERIS_TYPE": 0, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 0,
                      "OBJECT_ID": "", **o, "EPOCH": ep}
            sat = Satrec()
            sgp4_omm.initialize(sat, fields)
            omm = {k: o[k] for k in OMM_KEYS}
            omm["EPOCH"] = ep
            recs.append(dict(norad=int(o["NORAD_CAT_ID"]), name=str(o.get("OBJECT_NAME", "")),
                             cospar=o.get("OBJECT_ID"), kind="O", omm=omm, sat=sat,
                             epoch=dt.datetime.strptime(ep, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)))
        except Exception:
            bad += 1
    return recs, bad


def validate(src, text, now, max_age_days):
    """Разобрать и проверить выгрузку. Вернуть список годных записей или бросить ValueError."""
    recs, bad = (parse_tle if src["format"] == "tle" else parse_omm)(text)
    total = len(recs) + bad
    if not recs:
        raise ValueError(f"нет ни одной разборной записи ({text.strip()[:120]!r})")
    if bad / total > BAD_FORMAT_SHARE:
        raise ValueError(f"битых записей {bad} из {total} — выгрузка повреждена")
    good, stale, broken = [], 0, 0
    for r in recs:
        age = (now - r["epoch"]).total_seconds() / 86400
        if age > max_age_days or age < -2:
            stale += 1
        elif not sat_ok(r["sat"], now):
            broken += 1
        else:
            good.append(r)
    if not good:
        raise ValueError(f"все {total} записей отброшены (эпоха старше {max_age_days} сут: {stale}, SGP4: {broken})")
    log.info("  записей %d: годных %d, битый формат/контрольная сумма %d, старая эпоха %d, ошибка SGP4 %d",
             total, len(good), bad, stale, broken)
    return good


def atomic_write(path, data, mode=0o644):
    """Запись во временный файл рядом и os.replace: читатель видит либо старый, либо новый файл целиком."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def recent_cache(path):
    """Кэш выгрузки моложе REUSE_SECONDS — (содержимое, возраст в минутах), иначе None."""
    try:
        age = time.time() - os.path.getmtime(path)
        if age < REUSE_SECONDS:
            with open(path, encoding="utf-8") as f:
                return json.load(f), int(age // 60)
    except (OSError, ValueError):
        pass
    return None


def collect(cfg, state_dir, now, max_age_days, domain):
    """Скачать и проверить все источники. Выгрузка моложе REUSE_SECONDS берётся из кэша без запроса.
    При неудаче — последняя удачная копия из кэша (если ещё годна)."""
    ua = cfg["http"]["user_agent"].format(domain=domain or "localhost")
    cache_dir = os.path.join(state_dir, "sources")
    os.makedirs(cache_dir, exist_ok=True)
    results = []
    for src in cfg["sources"]:
        log.info("Источник %s (%s)", src["id"], src.get("title", ""))
        cache = os.path.join(cache_dir, src["id"] + ".json")
        fresh, recs, url, retrieved = False, None, None, None
        rc = recent_cache(cache)
        if rc:
            try:
                recs = validate(src, rc[0]["text"], now, max_age_days)
                fresh, url, retrieved = True, rc[0]["url"], rc[0]["retrievedAt"]
                log.info("  выгрузке %d мин — беру сохранённую, источник не запрашиваю", rc[1])
            except Exception as e:
                log.warning("  сохранённая выгрузка не годится (%s) — запрашиваю заново", e)
                recs = None
        if recs:
            for r in recs:
                r["source"] = src["id"]
            results.append(dict(src=src, recs=recs, fresh=fresh, url=url, retrievedAt=retrieved))
            continue
        try:
            got = fetch_source(src, cfg["http"], ua)
            if got is None:
                log.info("  пропущен: не заданы SPACETRACK_USER/SPACETRACK_PASS")
                continue
            text, url = got
            recs = validate(src, text, now, max_age_days)
            fresh, retrieved = True, now.date().isoformat()
            atomic_write(cache, json.dumps({"url": url, "retrievedAt": retrieved, "text": text}, ensure_ascii=False), 0o600)
        except Exception as e:
            log.warning("  НЕ ПРИНЯТ: %s", e)
            if os.path.exists(cache):
                try:
                    with open(cache, encoding="utf-8") as f:
                        c = json.load(f)
                    recs = validate(src, c["text"], now, max_age_days)
                    url, retrieved = c["url"], c["retrievedAt"]
                    log.warning("  использую последнюю удачную выгрузку от %s", retrieved)
                except Exception as e2:
                    log.warning("  кэш тоже не годится: %s", e2)
                    recs = None
        if recs:
            for r in recs:
                r["source"] = src["id"]
            results.append(dict(src=src, recs=recs, fresh=fresh, url=url, retrievedAt=retrieved))
    return results


def merge_pool(results):
    pool = {}
    for res in results:
        for r in res["recs"]:
            cur = pool.get(r["norad"])
            if cur is None or (r["epoch"], r["kind"] == "T") > (cur["epoch"], cur["kind"] == "T"):
                pool[r["norad"]] = r
    return pool


# ---------- сборка HTML ----------

def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=UTC) if s else None
    except ValueError:
        return None


def block_re(block_id):
    return re.compile(r'(<script\b[^>]*\bid=(["\'])' + re.escape(block_id) + r'\2[^>]*>)(.*?)(</script\s*>)', re.S | re.I)


def find_blocks(page):
    """id -> type для всех <script id="data-..."> шаблона."""
    out = {}
    for m in re.finditer(r'<script\b([^>]*)>', page, re.I):
        attrs = m.group(1)
        mid = re.search(r'\bid=(["\'])(data-[^"\']+)\1', attrs)
        if mid:
            mt = re.search(r'\btype=(["\'])([^"\']+)\1', attrs)
            out[mid.group(2)] = (mt.group(2).lower() if mt else "")
    return out


def get_block(page, block_id):
    m = block_re(block_id).search(page)
    return m.group(3) if m else None


def put_block(page, block_id, content):
    """Заменить ТОЛЬКО содержимое между открывающим и закрывающим тегом блока."""
    m = block_re(block_id).search(page)
    return page[:m.start(3)] + content + page[m.end(3):]


def json_text(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/").replace("<!--", "<\\u0021--")   # не даём закрыть <script> изнутри


# ---------- состав систем по группам SATCAT ----------
# Системы реестра с select.satcatGroup (GPS, Galileo, станции…): состав берётся из SATCAT CelesTrak по тематической
# группе — небольшая выгрузка раз в сутки на группу; элементы орбит — из общего набора источников (GROUP=active).

SATCAT_URL = "https://celestrak.org/satcat/records.php?GROUP={group}&FORMAT=json"
ACTIVE_OPS = {"+", "P", "B", "S", "X"}   # действующие по коду состояния SATCAT
CATALOG_FIELDS = ["norad", "name", "cospar", "launchDate", "gcatProgram", "gcatCategory", "subtype",
                  "satcat[perigee,apogee,inc,period,ops,owner]", "elementsSource", "epoch", "elements"]


def satcat_systems(page):
    try:
        reg = json.loads(get_block(page, "registry") or "{}")
    except ValueError:
        return []
    return [s for s in reg.get("systems", []) if (s.get("select") or {}).get("satcatGroup") and s.get("dataKey")]


def collect_satcat(groups, http_cfg, state_dir, ua, now):
    """SATCAT по группам. Состав групп меняется редко, поэтому без повторов: выгрузка моложе REUSE_SECONDS
    берётся из кэша, а после первого отказа CelesTrak остальные группы сразу берутся из кэша, без запросов.
    Группа без данных пропускается (состав системы на странице тогда остаётся прежним)."""
    out = {}
    cache_dir = os.path.join(state_dir, "sources")
    os.makedirs(cache_dir, exist_ok=True)
    once = {**http_cfg, "retries": 0}
    down = None   # причина первого отказа: дальше не запрашиваем
    for g in sorted(groups):
        url = SATCAT_URL.format(group=urllib.parse.quote(g))
        cache = os.path.join(cache_dir, f"satcat-{g}.json")
        rc = recent_cache(cache)
        if rc and rc[0].get("recs"):
            c = rc[0]
            out[g] = {"recs": c["recs"], "url": c["url"], "retrievedAt": c["retrievedAt"]}
            log.info("  SATCAT %s: выгрузке %d мин — беру сохранённую", g, rc[1])
            continue
        try:
            if down:
                raise RuntimeError(f"не запрашиваю, CelesTrak недоступен ({down})")
            recs = json.loads(http_get(url, once, ua))
            if not isinstance(recs, list) or not recs:
                raise ValueError("пустой ответ")
            retrieved = now.date().isoformat()
            atomic_write(cache, json.dumps({"url": url, "retrievedAt": retrieved, "recs": recs}, ensure_ascii=False), 0o600)
            log.info("  SATCAT %s: %d записей", g, len(recs))
        except Exception as e:
            log.warning("  SATCAT %s НЕ ПОЛУЧЕН: %s", g, e)
            down = down or str(e)
            try:
                with open(cache, encoding="utf-8") as f:
                    c = json.load(f)
                recs, url, retrieved = c["recs"], c["url"], c["retrievedAt"]
                log.warning("  использую последнюю удачную выгрузку от %s", retrieved)
            except (OSError, ValueError, KeyError):
                continue
        out[g] = {"recs": recs, "url": url, "retrievedAt": retrieved}
    return out


def satcat_entry(group, g):
    return {"id": f"celestrak-satcat-{group}", "tier": 2, "kind": "catalog", "publisher": "CelesTrak SATCAT",
            "title": f"SATCAT, группа {group}: состав, владелец, дата запуска, перигей, апогей, наклонение, период",
            "url": g["url"], "retrievedAt": g["retrievedAt"]}


def row_elements(r):
    return ["T", r["l1"], r["l2"]] if r["kind"] == "T" else ["O"] + [r["omm"][k] for k in OMM_KEYS]


def rebuild_satcat_blocks(page, satcat, pool, entries):
    """Состав систем с select.satcatGroup: действующие спутники группы (с фильтром по имени или NORAD), которых нет
    в других системах страницы (у российских систем приоритет). Без элементов орбит аппарат не показывается."""
    systems = satcat_systems(page)
    own = {s["dataKey"] for s in systems}
    taken = set()
    for bid, bt in find_blocks(page).items():
        if bt != "application/json" or bid in own:
            continue
        try:
            obj = json.loads(get_block(page, bid))
        except ValueError:
            continue
        if "satellites" in obj:
            taken.update(x.get("noradId") for x in obj["satellites"])
        elif "rows" in obj and "norad" in (obj.get("fields") or []):
            i = obj["fields"].index("norad")
            taken.update(r[i] for r in obj["rows"])
    for s in systems:
        sel, bid = s["select"], s["dataKey"]
        g, body = satcat.get(sel["satcatGroup"]), get_block(page, bid)
        if g is None or body is None:
            continue
        b = json.loads(body)
        if b.get("fields") != CATALOG_FIELDS:
            log.warning("  %s: неожиданные поля блока — состав не пересобран", bid)
            continue
        old = {r[0]: r for r in b.get("rows", [])}
        pat = re.compile(sel["namePattern"]) if sel.get("namePattern") else None
        only = set(sel.get("norad") or [])
        rows, noel = [], 0
        for x in g["recs"]:
            n = x.get("NORAD_CAT_ID")
            if not isinstance(n, int) or n in taken or (only and n not in only):
                continue
            if x.get("OBJECT_TYPE") != "PAY" or x.get("DECAY_DATE") or x.get("OPS_STATUS_CODE") not in ACTIVE_OPS:
                continue
            if pat and not pat.search(x.get("OBJECT_NAME") or ""):
                continue
            r, prev = pool.get(n), old.get(n)
            if r:
                el = (r["source"], iso(r["epoch"]), row_elements(r))
            elif prev and prev[10]:
                el = (prev[8], prev[9], prev[10])
            else:
                noel += 1
                continue
            sc = [x.get("PERIGEE"), x.get("APOGEE"), x.get("INCLINATION"), x.get("PERIOD"), x.get("OPS_STATUS_CODE"), x.get("OWNER")]
            rows.append([n, x.get("OBJECT_NAME"), x.get("OBJECT_ID"), x.get("LAUNCH_DATE") or None, None, None, None, sc, *el])
            taken.add(n)
        rows.sort(key=lambda r: (r[3] or "", r[0]))
        b["rows"] = rows
        e = satcat_entry(sel["satcatGroup"], g)
        b["sources"] = [x for x in b.get("sources", []) if not x.get("id", "").startswith("celestrak-satcat-")] + [e]
        upsert_sources(b["sources"], entries, {r[8] for r in rows})
        page = put_block(page, bid, json_text(b))
        log.info("  %s (SATCAT %s): аппаратов %d%s", bid, sel["satcatGroup"], len(rows), f", без элементов орбит {noel}" if noel else "")
    return page



# ---------- история высоты орбиты ----------

HISTORY_DAYS = 32

def _mean_alt_km(sat):
    try:
        alt = (sat.a - 1.0) * 6378.135      # большая полуось: ER -> км, минус радиус Земли
        return alt if 120 < alt < 500000 else None
    except Exception:
        return None


def update_history(page, pool, now, state_dir):
    """Накапливает среднюю высоту орбиты по дням (блок data-history), кроме массовых систем.
       Полностью изолирована: любая ошибка логируется и НЕ влияет на публикацию страницы."""
    bid = "data-history"
    if not block_re(bid).search(page):
        return page
    try:
        tracked = set()
        for b, bt in find_blocks(page).items():
            if bt != "application/json" or b in ("data-meta", "data-history", "data-starlink"):
                continue
            obj = json.loads(get_block(page, b))
            if "satellites" in obj:
                tracked.update(s["noradId"] for s in obj["satellites"] if s.get("noradId"))
            elif "rows" in obj and "norad" in (obj.get("fields") or []):
                i = obj["fields"].index("norad")
                tracked.update(r[i] for r in obj["rows"])
        path = os.path.join(state_dir, "alt-history.json")
        hist = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                hist = json.load(f)
        for norad in tracked:
            r = pool.get(norad)
            if not r:
                continue
            alt = _mean_alt_km(r["sat"])
            if alt is None:
                continue
            d = r["epoch"].date().isoformat()
            s = hist.setdefault(str(norad), {"s": []})["s"]
            if s and s[-1][0] == d:
                s[-1][1] = round(alt, 1)        # та же дата эпохи — обновляем значение
            else:
                s.append([d, round(alt, 1)])
            hist[str(norad)]["s"] = s[-HISTORY_DAYS:]
        hist = {k: v for k, v in hist.items() if int(k) in tracked}      # забываем исчезнувшие аппараты
        atomic_write(path, json.dumps(hist, ensure_ascii=False), 0o600)
        emb = {k: v["s"] for k, v in hist.items() if len(v.get("s", [])) >= 2}
        page = put_block(page, bid, json_text(emb))
        log.info("  data-history: аппаратов с историей %d из %d отслеживаемых", len(emb), len(tracked))
    except Exception as e:
        log.warning("  data-history пропущена (на публикацию не влияет): %s", e)
    return page


# ---------- новостной фид (RSS) ----------

NEWS_MAX = 36
NEWS_SUMMARY = 240
NEWS_KW = re.compile(r"(косм|ракет|спутник|орбит|\bзапуск|МКС|роскосмос|starship|spacex|союз|ангар|протон|\bлун|\bмарс|"
                     r"астронавт|космонавт|starlink|байконур|восточн|space|rocket|satellite|orbit|launch|nasa|"
                     r"\besa\b|lunar|mars|moon|spacecraft)", re.I)
_ATOM = "{http://www.w3.org/2005/Atom}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
NEWS_IMG_W = 480            # ширина превью: источник отдаёт уменьшенную копию по ?w= (своего ресайза нет — без Pillow)
NEWS_IMG_MAX = 250_000      # больше — не сохраняем
NEWS_IMG_DIR = "news"       # каталог превью рядом со страницей; браузер не ходит на чужие сайты (CSP — только свой)
# хвосты и префиксы лент, которые не несут смысла: «Description …» у NASA, «The post … appeared first on …» у WordPress
_NEWS_JUNK = re.compile(r"^(Description|Описание)\s+|\s*The post .{0,300}? appeared first on [^.]{1,80}\.?\s*$", re.I)


def _news_strip(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def _news_image(it):
    """Картинка новости: media:content/thumbnail, enclosure с type image/*, иначе первая <img> в тексте записи."""
    for e in it.findall(_MEDIA + "content") + it.findall(_MEDIA + "thumbnail") + it.findall("enclosure"):
        u, ty = e.get("url"), e.get("type") or ""
        if u and (not ty or ty.startswith("image/")):
            return u
    for tag in (_CONTENT + "encoded", "description"):
        e = it.find(tag)
        m = re.search(r'<img[^>]+src="([^"]+)"', e.text or "") if e is not None else None
        if m:
            return html.unescape(m.group(1))
    return None


def _news_text(it, tag):
    e = it.find(tag)
    if e is None:
        e = it.find(_ATOM + tag)
    return e.text if e is not None and e.text else None


def _news_date(it):
    raw = _news_text(it, "pubDate") or _news_text(it, "updated") or _news_text(it, "published")
    if not raw:
        return None
    try:
        d = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return (d.replace(tzinfo=UTC) if d.tzinfo is None else d).astimezone(UTC)


def parse_feed(text, feed):
    root = ET.fromstring(text)
    out = []
    for it in (root.findall(".//item") or root.findall(".//" + _ATOM + "entry")):
        title = _news_strip(_news_text(it, "title"))
        le = it.find("link")
        link = le.text.strip() if le is not None and le.text else None
        if not link:
            for l in it.findall(_ATOM + "link"):
                if l.get("rel") in (None, "alternate") and l.get("href"):
                    link = l.get("href"); break
        if not (title and link and link.startswith("http")):
            continue
        summary = _NEWS_JUNK.sub("", _news_strip(_news_text(it, "description") or _news_text(it, "summary") or "")).strip()
        if feed.get("filter") and not NEWS_KW.search(title + " " + summary):
            continue
        if len(summary) > NEWS_SUMMARY:
            summary = summary[:NEWS_SUMMARY].rsplit(" ", 1)[0] + "…"
        when = _news_date(it)
        item = {"t": title, "s": summary, "u": link, "d": iso(when) if when else None,
                "src": feed["name"], "lang": feed.get("lang", "")}
        # картинки — только у источников, где они в общественном достоянии (sources.yml: images), без исключений images_skip
        if feed.get("images") and not (feed.get("images_skip") and re.search(feed["images_skip"], title)):
            img = _news_image(it)
            # эмблемы и логотипы — не фото: эмблему NASA нельзя ставить так, будто ведомство поддерживает сайт
            if img and img.startswith("https://") and not re.search(r"meatball|insignia|logo|worm", img, re.I):
                item["isrc"] = img
        out.append(item)
    return out


def _news_image_url(u):
    """Уменьшенная копия у источника: ?w=NEWS_IMG_W (NASA: assets.science.nasa.gov, wp-content), у медиатеки NASA — ~small."""
    p = urllib.parse.urlsplit(u)
    path = re.sub(r"~(large|orig|medium)\.(jpg|jpeg|png)$", r"~small.\2", p.path)
    q = "" if path != p.path else urllib.parse.urlencode({"w": NEWS_IMG_W})
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, q, ""))


def publish_news_images(news, cfg, ua, out_dir):
    """Превью новостей в <out>/news/<хеш>.<jpg|png|webp>; в записи — путь "i", внешний адрес убирается.
    Изолирована: сбой одной картинки — новость без фото. Файлы, на которые не ссылается ни одна новость, удаляются."""
    d = os.path.join(out_dir, NEWS_IMG_DIR)
    http_cfg = dict(cfg["http"]); http_cfg["retries"] = 0
    keep, got = set(), 0
    for it in news or []:
        src = it.pop("isrc", None)
        if it.get("i"):
            keep.add(os.path.basename(it["i"]))
        if not src or it.get("i"):
            continue
        try:
            url = _news_image_url(src)
            body = http_get(url, http_cfg, ua, raw=True)
            ext = ("jpg" if body[:2] == bytes([0xFF, 0xD8]) else "png" if body[:8] == bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
                   else "webp" if body[:4] == b"RIFF" and body[8:12] == b"WEBP" else None)
            if not ext or len(body) > NEWS_IMG_MAX:
                raise ValueError(f"{'не картинка' if not ext else f'{len(body)} байт'}")
            name = f"{hashlib.sha1(src.encode()).hexdigest()[:12]}.{ext}"
            os.makedirs(d, exist_ok=True)
            if not os.path.exists(os.path.join(d, name)):
                atomic_write(os.path.join(d, name), body)
            it["i"] = f"{NEWS_IMG_DIR}/{name}"; keep.add(name); got += 1
        except Exception as e:
            log.info("  превью новости пропущено (%s): %s", src.split("?")[0][:100], e)
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n not in keep:
                os.unlink(os.path.join(d, n))
    log.info("  превью новостей: %d", len(keep))
    return got


def publish_models(src, out):
    """3D-модели (models/*.glb, models/iss/*.glb) — рядом со страницей: окно 3D грузит их по /models/….
    Копируются только новые и изменённые файлы, удалённые из репозитория — убираются. Нет каталога — пропуск."""
    if not src or not os.path.isdir(src):
        return 0
    dst = os.path.join(out, "models")
    if os.path.realpath(src) == os.path.realpath(dst):
        return 0
    copied, keep = 0, set()
    for dp, _, files in os.walk(src):
        for f in files:
            if not f.endswith(".glb"):
                continue
            s_, rel = os.path.join(dp, f), os.path.relpath(os.path.join(dp, f), src)
            d = os.path.join(dst, rel)
            keep.add(rel)
            if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s_) and os.path.getmtime(d) >= os.path.getmtime(s_):
                continue
            os.makedirs(os.path.dirname(d), exist_ok=True)
            with open(s_, "rb") as fh:
                atomic_write(d, fh.read())
            copied += 1
    for dp, _, files in os.walk(dst):
        for f in files:
            rel = os.path.relpath(os.path.join(dp, f), dst)
            if f.endswith(".glb") and rel not in keep:
                os.remove(os.path.join(dp, f))
    return copied


def jpeg_size(b):
    """(ширина, высота) JPEG по маркеру SOF; None — не JPEG."""
    if b[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xD8, 0x01, 0xFF) or 0xD0 <= m <= 0xD7:
            i += 2 if m != 0xFF else 1
            continue
        if m in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
    return None


def publish_clouds(cfg, ua, out_dir, today):
    """Облака 3D-глобуса (sources.yml: clouds) в <out>/clouds/: файлы с датой и latest.json.
    Хранятся текущий и предыдущий наборы — открытые вкладки могут догружать вчерашний."""
    c = cfg.get("clouds")
    if not c:
        return
    d = os.path.join(out_dir, "clouds")
    os.makedirs(d, exist_ok=True)
    http_cfg = dict(cfg["http"]); http_cfg["retries"] = 1       # не критично — без долгих ретраев
    files = {}
    for w in c["sizes"]:
        body = http_get(c["url"].format(w=w, h=w // 2), http_cfg, ua, raw=True)
        if jpeg_size(body) != (w, w // 2):
            raise ValueError(f"облака {w}: ожидался JPEG {w}×{w // 2}, получено {jpeg_size(body)}")
        name = f"clouds-{w}.{today}.jpg"
        atomic_write(os.path.join(d, name), body)
        files[str(w)] = name
    latest = os.path.join(d, "latest.json")
    keep = set(files.values())
    try:
        with open(latest, encoding="utf-8") as f:
            keep |= set(json.load(f).get("files", {}).values())
    except (OSError, ValueError):
        pass
    atomic_write(latest, json.dumps({"date": today, "files": files, "source": c["url"], "levels": c.get("levels"),
                                     "attribution": "Contains modified EUMETSAT data"}, ensure_ascii=False))
    for n in os.listdir(d):
        if n.startswith("clouds-") and n not in keep:
            os.unlink(os.path.join(d, n))
    log.info("  облака глобуса: %s", ", ".join(files.values()))


def fetch_news(cfg, ua, state_dir):
    """Собрать новости из RSS. Изолирована: при полном сбое вернуть кэш, при его отсутствии — []."""
    feeds = cfg.get("news") or []
    if not feeds:
        return None
    http_cfg = dict(cfg["http"]); http_cfg["retries"] = 1       # новости не критичны — без долгих ретраев
    cache = os.path.join(state_dir, "news.json")
    items, ok = [], 0
    for feed in feeds:
        try:
            got = parse_feed(http_get(feed["url"], http_cfg, ua), feed)
            items.extend(got); ok += 1
            log.info("  новости %s: %d", feed["id"], len(got))
        except Exception as e:
            log.warning("  новости %s пропущены: %s", feed.get("id"), e)
    if not ok:
        try:
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["d"] or "", reverse=True):
        if it["u"] not in seen:
            seen.add(it["u"]); uniq.append(it)
    uniq = uniq[:NEWS_MAX]
    try:
        atomic_write(cache, json.dumps(uniq, ensure_ascii=False), 0o600)
    except Exception:
        pass
    return uniq


def element_for(r, today, policy):
    age = (dt.datetime.now(UTC) - r["epoch"]).total_seconds() / 86400
    e = {"format": "TLE" if r["kind"] == "T" else "OMM", "epoch": iso(r["epoch"]), "source": r["source"],
         "retrievedAt": today, "freshness": "current" if age <= policy.get("currentMaxAgeDays", 7) else "stale"}
    if r["kind"] == "T":
        e.update(tle=[r["l1"], r["l2"]], checksumOk=True)
    else:
        e["omm"] = {"OBJECT_NAME": r["name"], "OBJECT_ID": r.get("cospar"), "NORAD_CAT_ID": r["norad"], **r["omm"]}
    return e


def source_entries(results, today):
    return [{"id": res["src"]["id"], "tier": 2, "kind": "catalog",
             "publisher": "CelesTrak" if res["src"]["provider"] == "celestrak" else "USSPACECOM via Space-Track.org",   # требование Space-Track: указывать источник
             "title": res["src"].get("title", res["src"]["id"]), "url": res["url"], "retrievedAt": res["retrievedAt"]}
            for res in results]


def upsert_sources(lst, entries, used):
    have = {s.get("id"): i for i, s in enumerate(lst)}
    for e in entries:
        if e["id"] not in used:
            continue
        if e["id"] in have:
            lst[have[e["id"]]] = e
        else:
            lst.append(e)


def update_constellation(m, pool, now, entries):
    today, used, n = now.date().isoformat(), set(), 0
    policy = (m.get("dataset") or {}).get("freshnessPolicy") or {}
    for s in m.get("satellites", []):
        r = pool.get(s.get("noradId"))
        old = parse_iso((s.get("elements") or {}).get("epoch"))
        if r and (old is None or r["epoch"] > old + dt.timedelta(seconds=1)):
            s["elements"] = element_for(r, today, policy)
            used.add(r["source"])
            n += 1
    if n:
        upsert_sources(m.setdefault("sources", []), entries, used)
        ds = m.setdefault("dataset", {})
        ds["generatedAt"] = iso(now)
        sats = m.get("satellites", [])
        cur = policy.get("currentMaxAgeDays", 7)
        ds["elementsCoverage"] = {
            "total": len(sats),
            "withElements": sum(1 for s in sats if s.get("elements")),
            "current": sum(1 for s in sats if s.get("elements") and
                           (now - (parse_iso(s["elements"].get("epoch")) or now - dt.timedelta(days=999))).days <= cur)}
    return n


def update_catalog(b, pool, now, entries):
    f = b.get("fields") or []
    try:
        i_norad, i_src, i_epoch, i_el = f.index("norad"), f.index("elementsSource"), f.index("epoch"), f.index("elements")
    except ValueError:
        return 0
    used, n = set(), 0
    for row in b.get("rows", []):
        r = pool.get(row[i_norad])
        old = parse_iso(row[i_epoch])
        if r and (old is None or r["epoch"] > old + dt.timedelta(seconds=1)):
            row[i_src], row[i_epoch] = r["source"], iso(r["epoch"])
            row[i_el] = ["T", r["l1"], r["l2"]] if r["kind"] == "T" else ["O"] + [r["omm"][k] for k in OMM_KEYS]
            used.add(r["source"])
            n += 1
    if n:
        upsert_sources(b.setdefault("sources", []), entries, used)
        b["generatedAt"] = iso(now)
    return n


def tle_text(results, block_id):
    """3LE для text/plain-блока: свежайшая запись на NORAD из источников, у которых этот блок в blocks."""
    pool = merge_pool([r for r in results if block_id in (r["src"].get("blocks") or [])])
    lines, skipped = [], 0
    for norad in sorted(pool):
        r = pool[norad]
        if r["kind"] != "T":
            skipped += 1     # шестизначный NORAD в 3LE не записать
            continue
        name = re.sub(r"[<>&\x00-\x1f]", " ", r["name"] or f"NORAD {norad}").strip()
        lines += [name, r["l1"], r["l2"]]
    if skipped:
        log.info("  %s: %d аппаратов только в OMM, в 3LE не попали", block_id, skipped)
    return ("\n" + "\n".join(lines) + "\n") if lines else None, len(lines) // 3


def set_last_updated(page, now):
    stamp = now.strftime("%d.%m.%Y %H:%M")

    def repl(m):
        tag = re.sub(r'\s+datetime=(["\']).*?\1', "", m.group(1))
        if m.group(2).lower() == "time":
            tag = tag[:-1] + f' datetime="{iso(now)}">'
        return tag + stamp + m.group(4)
    return re.sub(r'(<(\w+)\b[^>]*\bid=(["\'])last-updated\3[^>]*>).*?(</\2>)', repl, page, count=1, flags=re.S)


def ensure_seo(page, domain, now):
    """Добавить в <head> недостающие description/canonical/OG-теги; og:updated_time — при свежих данных (now)."""
    tags = []
    if now:
        page = re.sub(r'\s*<meta\s+property="og:updated_time"[^>]*>', "", page)
        tags.append(f'<meta property="og:updated_time" content="{iso(now)}">')
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    title = html.unescape(m.group(1).strip()) if m else "Рассвет — трекер спутников"
    base = f"https://{domain}/" if domain else None
    want = [
        (r'<meta\s+name="description"', f'<meta name="description" content="{html.escape(SEO_DESCRIPTION)}">'),
        (r'<link\s+rel="icon"', '<link rel="icon" href="/favicon.ico" sizes="any">'),
        (r'<meta\s+property="og:type"', '<meta property="og:type" content="website">'),
        (r'<meta\s+property="og:site_name"', '<meta property="og:site_name" content="Рассвет">'),
        (r'<meta\s+property="og:locale"', '<meta property="og:locale" content="ru_RU">'),
        (r'<meta\s+property="og:title"', f'<meta property="og:title" content="{html.escape(title)}">'),
        (r'<meta\s+property="og:description"', f'<meta property="og:description" content="{html.escape(SEO_DESCRIPTION)}">'),
        (r'<meta\s+name="twitter:card"', '<meta name="twitter:card" content="summary_large_image">'),
    ]
    if base:
        want += [
            (r'<link\s+rel="canonical"', f'<link rel="canonical" href="{base}">'),
            (r'<meta\s+property="og:url"', f'<meta property="og:url" content="{base}">'),
            (r'<meta\s+property="og:image"', f'<meta property="og:image" content="{base}og.png">\n'
                                             '<meta property="og:image:width" content="1200">\n'
                                             '<meta property="og:image:height" content="630">'),
        ]
    tags += [tag for pat, tag in want if not re.search(pat, page, re.I)]
    return re.sub(r"</head>", "\n".join(tags) + "\n</head>", page, count=1, flags=re.I)


def build(template, results, now, domain, stamp=True, state_dir=None, news=None, satcat=None):
    """stamp=False — данные не свежие: дату обновления на странице не трогаем."""
    page = template
    pool = merge_pool(results)
    entries = source_entries(results, now.date().isoformat())
    if satcat:
        page = rebuild_satcat_blocks(page, satcat, pool, entries)
    blocks = find_blocks(page)
    changed = 0
    for bid, btype in blocks.items():
        if bid == "data-meta":
            continue
        if btype == "text/plain":
            text, n = tle_text(results, bid)
            if text is None:
                log.info("  %s: нет данных от источников — блок оставлен как в шаблоне", bid)
                continue
            page = put_block(page, bid, text)
            log.info("  %s (3LE): %d аппаратов", bid, n)
            changed += 1
        elif btype == "application/json":
            obj = json.loads(get_block(page, bid))
            if "satellites" in obj:
                n = update_constellation(obj, pool, now, entries)
            elif "rows" in obj:
                n = update_catalog(obj, pool, now, entries)
            else:
                continue
            if n:
                page = put_block(page, bid, json_text(obj))
                changed += 1
            log.info("  %s (JSON): обновлены элементы у %d аппаратов", bid, n)
    if state_dir:
        page = update_history(page, pool, now, state_dir)
    if news is not None and "data-news" in blocks:
        page = put_block(page, "data-news", json_text(news))
        log.info("  data-news: новостей %d", len(news))
    if stamp and "data-meta" in blocks:
        meta = json.loads(get_block(page, "data-meta") or "{}")
        meta["generatedAt"] = iso(now)
        extra = [satcat_entry(g, v) for g, v in sorted((satcat or {}).items())]
        upsert_sources(meta.setdefault("sources", []), entries + extra, {e["id"] for e in entries + extra})
        page = put_block(page, "data-meta", json_text(meta))
    if stamp:
        page = set_last_updated(page, now)
    page = ensure_seo(page, domain, now if stamp else None)
    return page, changed


def check_built(template, page):
    """Последний рубеж перед публикацией: разметка цела, блоки на месте и разбираются."""
    tb, pb = find_blocks(template), find_blocks(page)
    if tb != pb:
        raise ValueError(f"набор data-блоков изменился: {sorted(set(tb) ^ set(pb))}")
    if len(re.findall(r"<script\b", template, re.I)) != len(re.findall(r"<script\b", page, re.I)):
        raise ValueError("изменилось число тегов <script>")
    if re.search(r"</html>", template, re.I) and not re.search(r"</html>\s*$", page, re.I):
        raise ValueError("документ обрезан")
    if len(page) < 0.5 * len(template):
        raise ValueError("результат подозрительно мал")
    for bid, btype in pb.items():
        body = get_block(page, bid)
        if btype == "application/json":
            json.loads(body)
        elif btype == "text/plain" and body.strip():
            recs, bad = parse_tle(body)
            if bad or not recs:
                raise ValueError(f"{bid}: 3LE не разбирается")


EXTERNAL_BLOCKS = ("data-starlink", "geo-detail")   # крупные блоки (Starlink ~3 МБ, регионы и города ~1,3 МБ): отдельными файлами, страница догружает после первого кадра


def externalize(page, out_dir):
    """Выносит крупные JSON-блоки в файлы <id>.<hash>.json (+ сжатая копия .gz); в блоке остаётся {"src": имя}.
    Вызывается после check_built — проверка видит страницу целиком. Файлы старше двух суток удаляются."""
    for bid in EXTERNAL_BLOCKS:
        body = get_block(page, bid)
        if not body or not body.strip() or json.loads(body).get("src"):
            continue
        raw = body.encode("utf-8")
        name = f"{bid}.{hashlib.sha256(raw).hexdigest()[:10]}.json"
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            atomic_write(path, raw)
            atomic_write(path + ".gz", gzip.compress(raw, 9, mtime=0))
        page = put_block(page, bid, json.dumps({"src": name}))
        for n in os.listdir(out_dir):
            fp = os.path.join(out_dir, n)
            if n.startswith(bid + ".") and not n.startswith(name) and time.time() - os.path.getmtime(fp) > 2 * 86400:
                os.unlink(fp)
        log.info("  %s: вынесен в %s (%d КБ)", bid, name, len(raw) // 1024)
    return page


def render_static(static_dir, name, domain, today):
    with open(os.path.join(static_dir, name), encoding="utf-8") as f:
        return f.read().replace("REPLACE_DOMAIN", domain).replace("REPLACE_LASTMOD", today)


# ---------- запуск ----------

def run_once(args, cfg):
    now = dt.datetime.now(UTC).replace(microsecond=0)
    domain = os.environ.get("DOMAIN", "").strip()
    if domain == "REPLACE_DOMAIN":
        domain = ""
    max_age = env_int("MAX_EPOCH_AGE_DAYS", 30)
    log.info("=== обновление %s (MAX_EPOCH_AGE_DAYS=%d%s) ===", iso(now), max_age, ", DRY-RUN" if args.dry_run else "")

    results = collect(cfg, os.path.join(args.data, "state"), now, max_age, domain)
    fresh = [r["src"]["id"] for r in results if r["fresh"]]
    log.info("Свежих источников: %d из %d (%s)", len(fresh), len(cfg["sources"]), ", ".join(fresh) or "—")
    idx = os.path.join(args.out, "index.html")
    inputs_changed = not os.path.exists(idx) or any(
        os.path.getmtime(p) > os.path.getmtime(idx) for p in (args.template, args.sources))
    if not fresh:
        if not inputs_changed:
            log.error("Ни один источник не дал свежих проверенных данных — публикация пропущена, сайт остаётся на предыдущей версии")
            return 1
        log.warning("Свежих данных нет, но опубликованной версии нет или шаблон/sources.yml новее неё — "
                    "собираю из шаблона и последних удачных выгрузок, дату обновления не меняю")

    with open(args.template, encoding="utf-8") as f:
        template = f.read()
    log.info("Сборка из %s", args.template)
    state_dir = os.path.join(args.data, "state")
    try:
        ua = cfg["http"]["user_agent"].format(domain=domain or "localhost")
        news = fetch_news(cfg, ua, state_dir)
    except Exception as e:
        log.warning("Новости пропущены (на публикацию не влияет): %s", e)
        news = None
    try:
        if news and not args.dry_run:
            publish_news_images(news, cfg, ua, args.out)
    except Exception as e:
        log.warning("Превью новостей пропущены (на публикацию не влияет): %s", e)
    for it in news or []:
        it.pop("isrc", None)
    groups = {sy["select"]["satcatGroup"] for sy in satcat_systems(template)}
    satcat = collect_satcat(groups, cfg["http"], state_dir, ua, now) if groups else {}
    page, changed = build(template, results, now, domain, stamp=bool(fresh), state_dir=state_dir, news=news, satcat=satcat)
    try:
        check_built(template, page)
    except Exception as e:
        log.error("Собранная страница не прошла проверку (%s) — публикация пропущена", e)
        return 2

    if args.dry_run:
        out = os.path.join(args.data, "state", "dry-run")
        os.makedirs(out, exist_ok=True)
        atomic_write(os.path.join(out, "index.html"), page)
        log.info("DRY-RUN: обновлено блоков %d, результат %s (%d байт); в %s ничего не опубликовано",
                 changed, os.path.join(out, "index.html"), len(page.encode()), args.out)
        return 0

    os.makedirs(args.out, exist_ok=True)
    page = externalize(page, args.out)
    raw = page.encode("utf-8")
    atomic_write(os.path.join(args.out, "index.html"), raw)
    atomic_write(os.path.join(args.out, "index.html.gz"), gzip.compress(raw, 9, mtime=0))
    if domain:
        today = now.date().isoformat()
        for name in ("robots.txt", "sitemap.xml"):
            atomic_write(os.path.join(args.out, name), render_static(args.static, name, domain, today))
    for name in ("earth-day.jpg", "earth-night.jpg"):      # текстуры глобуса: статично, кладём в корень сайта
        try:
            src = os.path.join(args.static, name)
            dst = os.path.join(args.out, name)
            if os.path.exists(src) and (not os.path.exists(dst) or os.path.getsize(src) != os.path.getsize(dst)):
                with open(src, "rb") as f:
                    atomic_write(dst, f.read())
        except Exception as e:
            log.warning("  текстура %s не скопирована (на публикацию не влияет): %s", name, e)
    try:
        n = publish_models(args.models, args.out)
        if n:
            log.info("  3D-модели: скопировано файлов %d", n)
    except Exception as e:
        log.warning("  3D-модели не опубликованы (на страницу не влияет, окно 3D покажет схему): %s", e)
    try:
        publish_clouds(cfg, cfg["http"]["user_agent"].format(domain=domain or "localhost"), args.out, now.date().isoformat())
    except Exception as e:
        log.warning("  облака глобуса не обновлены (на публикацию не влияет, остаются прежние или запасные): %s", e)
    log.info("Опубликовано: блоков обновлено %d, %d байт", changed, len(raw))
    return 0


def locked_run(args, cfg):
    state = os.path.join(args.data, "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "update.lock"), "w") as lock:
        if fcntl:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log.warning("Обновление уже идёт в другом процессе — пропускаю")
                return 0
        try:
            return run_once(args, cfg)
        except Stop:
            raise
        except Exception:
            log.exception("Обновление упало — сайт остаётся на предыдущей версии")
            return 3


def needs_catchup(args):
    idx = os.path.join(args.out, "index.html")
    if not os.path.exists(idx):
        return True
    mt = os.path.getmtime(idx)
    if time.time() - mt > 24 * 3600:
        return True
    deps = [args.template, args.sources] + [os.path.join(args.static, n) for n in ("robots.txt", "sitemap.xml")]
    return any(os.path.exists(p) and os.path.getmtime(p) > mt for p in deps)


def sleep_until_hour(hour):
    now = dt.datetime.now(UTC)
    nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += dt.timedelta(days=1)
    log.info("Следующее обновление: %s", iso(nxt))
    while True:            # короткие шаги, чтобы переживать смену системного времени и быстро останавливаться
        left = (nxt - dt.datetime.now(UTC)).total_seconds()
        if left <= 0:
            return
        time.sleep(min(left, 300))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Обновление данных трекера «Рассвет»")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="одно обновление и выход")
    mode.add_argument("--loop", action="store_true", help="постоянная работа: раз в сутки в UPDATE_HOUR_UTC")
    mode.add_argument("--dry-run", action="store_true", help="всё, кроме публикации")
    ap.add_argument("--template", default="/app/template/rassvet-tracker.html")
    ap.add_argument("--static", default="/app/static")
    ap.add_argument("--models", default="/app/models", help="каталог 3D-моделей репозитория (models/); нет — пропуск")
    ap.add_argument("--sources", default=os.path.join(here, "sources.yml"))
    ap.add_argument("--out", default="/srv/www", help="каталог сайта")
    ap.add_argument("--data", default="/data", help="логи и состояние")
    args = ap.parse_args()

    setup_logging(args.data)

    def on_term(signum, frame):
        raise Stop()
    signal.signal(signal.SIGTERM, on_term)

    cfg = load_config(args.sources)
    try:
        if not args.loop:
            return locked_run(args, cfg)
        hour = env_int("UPDATE_HOUR_UTC", 3)
        if not 0 <= hour <= 23:
            raise SystemExit("UPDATE_HOUR_UTC должен быть 0–23")
        if needs_catchup(args):
            log.info("Опубликованная версия отсутствует, старше суток или старше шаблона — обновляю сразу")
            locked_run(args, cfg)
        while True:
            sleep_until_hour(hour)
            locked_run(args, cfg)
    except (Stop, KeyboardInterrupt):
        log.info("Остановка")
        return 0


if __name__ == "__main__":
    sys.exit(main())
