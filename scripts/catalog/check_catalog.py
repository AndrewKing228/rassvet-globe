#!/usr/bin/env python3
"""
Проверка каталога трекера: реестр систем и строки аппаратов прямо в странице (index.html или шаблон).
Когда запускать: после правки реестра или данных; git pushall запускает её сам на публикуемой странице.
    python scripts/catalog/check_catalog.py index.html
Код выхода 0 — ошибок нет (предупреждения допускаются), 1 — есть ошибки.

Правила (см. README, «Источники данных»):
- система с verifiedAt: у описания есть первичный источник или два вторичных с разных доменов, у каждого источника
  kind (primary|secondary), http(s)-ссылка и дата обращения;
- военная система (категория «Военные» или classification) помечена classification: "gcat" — назначение по GCAT,
  официально не подтверждено;
- система с select.satcatGroup: блок в формате каталога с источником SATCAT;
- система: region, type, country/country_en для навигации по стране и типу;
- аппарат: NORAD 1..999999 без повторов между системами, COSPAR ГГГГ-NNNA, даты ISO, элементы орбиты TLE или OMM;
- части моделей (models[].parts — узлы part:<id> в GLB, models[].markers) и типовые части схем (schematicParts):
  имена и тексты RU/EN, источники https, статья Википедии;
- 3D-модель (registry.models): аппарат есть в каталоге, у official/open — лицензия, автор и https-источник,
  файл models/<имя>.glb ≤ 1,5 МБ и ≤ 50 000 треугольников, все вместе ≤ 25 МБ, без расширений, требующих WebAssembly.
"""
import json, os, re, struct, sys, urllib.parse

CATALOG_FIELDS = ["norad", "name", "cospar", "launchDate", "gcatProgram", "gcatCategory", "subtype",
                  "satcat[perigee,apogee,inc,period,ops,owner]", "elementsSource", "epoch", "elements"]
COSPAR = re.compile(r"\d{4}-\d{3}[A-Z]{1,3}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
HEX = re.compile(r"#[0-9a-fA-F]{6}")
ACCURACY = ("official", "open", "schematic")
# обязательные расширения glTF, которые страница открывает без WebAssembly и внешних декодеров
MODEL_EXT_OK = {"KHR_mesh_quantization", "EXT_texture_webp", "KHR_texture_transform", "KHR_materials_unlit"}
MODEL_MAX_BYTES, MODEL_MAX_TRI, MODELS_MAX_TOTAL = 1_500_000, 50_000, 25_000_000
BUS_TYPES = ["leo-flat", "gnss", "geo-comm", "leo-small", "station"]   # схемы 3D-моделей в странице (BUS_MESH)
REGIONS = ["ru", "us", "eu", "cn", "jp", "in", "int"]   # навигация по стране в панели (REGIONS в странице)
STYPES = ["internet", "navigation", "comms", "eo", "meteo", "science", "stations", "military", "other"]   # тип системы (STYPES)


def blocks(page):
    out = {}
    for m in re.finditer(r'<script type="application/json" id="([^"]+)">(.*?)</script>', page, re.S):
        if m.group(1) not in out:          # первый — настоящий блок; дальше в коде бывают примеры разметки
            out[m.group(1)] = m.group(2)
    return out


def glb_stats(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        return None
    ln, = struct.unpack_from("<I", data, 12)
    js = json.loads(data[20:20 + ln])
    use = {}
    for n in js.get("nodes", []):
        if n.get("mesh") is not None:
            use[n["mesh"]] = use.get(n["mesh"], 0) + 1
    tri = 0
    for i, m in enumerate(js.get("meshes", [])):
        t = sum(js["accessors"][p.get("indices", p["attributes"]["POSITION"])]["count"] // 3 for p in m["primitives"] if p.get("mode", 4) == 4)
        tri += t * use.get(i, 0)
    parts = [n["name"][5:] for n in js.get("nodes", []) if str(n.get("name", "")).startswith("part:")]
    return {"bytes": len(data), "triangles": tri, "required": js.get("extensionsRequired", []), "parts": parts}


def check_part(tag, x, err):
    """Описание части модели или метки: имена и тексты на двух языках, источники https, статья Википедии."""
    E = lambda m: err.append(f"{tag} {x.get('id')}: {m}")
    for k in ("name", "name_en", "text", "text_en"):
        if not x.get(k):
            E(f"нет {k}")
    src = x.get("sources") or []
    if not src or not all(str(q.get("url", "")).startswith("https://") and q.get("title") for q in src):
        E("нужны источники sources: [{title, url https}]")
    w = x.get("wiki") or {}
    if not all(str((w.get(l) or {}).get("url", "")).startswith("https://") for l in ("ru", "en")):
        E("нужна статья Википедии wiki.ru и wiki.en (https)")


SCHEMATIC_PART_IDS = {"bus", "solar", "antenna", "dish", "navant", "payload", "truss", "modules"}   # части схем в странице (BUS_PARTS)


def check_models(reg, seen, root):
    err, total = [], 0
    have = {x.get("id") for x in reg.get("schematicParts", [])}
    for x in reg.get("schematicParts", []):
        check_part("schematicParts", x, err)
    if SCHEMATIC_PART_IDS - have:
        err.append(f"schematicParts: нет описаний для {sorted(SCHEMATIC_PART_IDS - have)}")
    for m in reg.get("models", []):
        tag = f"модель {m.get('file')}"
        E = lambda x: err.append(f"{tag}: {x}")
        for nr in [m.get("norad")] + list(m.get("norads") or []):
            if nr not in seen:
                E(f"аппарата NORAD {nr} нет в каталоге")
        if m.get("accuracy") not in ACCURACY:
            E(f"accuracy — одно из {ACCURACY}")
        if m.get("accuracy") in ("official", "open"):
            if not m.get("license") or not m.get("credit"):
                E("нужны license и credit")
            if not str(m.get("source_url", "")).startswith("https://"):
                E("нужен https-адрес источника (source_url)")
        if not (isinstance(m.get("center"), list) and len(m["center"]) == 3 and (m.get("radius") or 0) > 0):
            E("нужны center [x,y,z] и radius > 0 — по ним камера вписывает модель")
        f = str(m.get("file", ""))
        if not re.fullmatch(r"models/[a-z0-9-]+\.glb", f):
            E("файл — models/<имя>.glb")
            continue
        path = os.path.join(root, f)
        if not os.path.exists(path):
            E(f"файл не найден ({path})")
            continue
        st = glb_stats(path)
        if not st:
            E("не GLB")
            continue
        for x in m.get("parts", []) + m.get("markers", []):
            check_part(tag, x, err)
        if m.get("parts"):
            ids = {x.get("id") for x in m["parts"]}
            if set(st["parts"]) != ids:
                E(f"части в файле {sorted(st['parts'])} и в реестре {sorted(ids)} не совпадают")
        if m.get("detailDir"):
            for x in m.get("parts", []):
                if not x.get("detail"):
                    continue
                df = os.path.join(root, m["detailDir"], x["id"] + ".glb")
                ds = glb_stats(df) if os.path.exists(df) else None
                if not ds:
                    E(f"подробная часть {x['id']}: нет файла или не GLB ({df})")
                    continue
                total += ds["bytes"]
                if ds["bytes"] > MODEL_MAX_BYTES or ds["triangles"] > MODEL_MAX_TRI:
                    E(f"подробная часть {x['id']}: {ds['bytes']} байт, {ds['triangles']} треугольников — больше лимита")
                if [q for q in ds["required"] if q not in MODEL_EXT_OK]:
                    E(f"подробная часть {x['id']}: расширения, требующие WebAssembly")
                if ds["parts"] != [x["id"]]:
                    E(f"подробная часть {x['id']}: в файле части {ds['parts']}")
        for x in m.get("markers", []):
            pos = x.get("pos") or []
            pts = pos if pos and isinstance(pos[0], list) else [pos]
            if not all(isinstance(q, list) and len(q) == 3 for q in pts):
                E(f"метка {x.get('id')}: pos — [x,y,z] или список таких точек")
        total += st["bytes"]
        if st["bytes"] > MODEL_MAX_BYTES:
            E(f"{st['bytes']} байт > {MODEL_MAX_BYTES}")
        if st["triangles"] > MODEL_MAX_TRI:
            E(f"{st['triangles']} треугольников > {MODEL_MAX_TRI}")
        bad = [x for x in st["required"] if x not in MODEL_EXT_OK]
        if bad:
            E(f"обязательные расширения {bad} требуют WebAssembly или внешних декодеров")
    if total > MODELS_MAX_TOTAL:
        err.append(f"все модели вместе {total} байт > {MODELS_MAX_TOTAL}")
    return err


def check(page, root="."):
    err, warn = [], []
    B = blocks(page)
    try:
        reg = json.loads(B["registry"])
    except (KeyError, ValueError) as e:
        return [f"registry: нет или не JSON ({e})"], warn
    groups = {g["id"] for g in reg.get("groups", [])}
    seen, legacy = {}, 0
    for s in reg.get("systems", []):
        sid = s.get("id", "?")
        E = lambda m: err.append(f"{sid}: {m}")
        for k in ("group", "category", "operator", "dataKey", "format"):
            if not s.get(k):
                E(f"нет поля {k}")
        if s.get("group") not in groups:
            E(f"группа {s.get('group')!r} не описана в groups")
        if not (s.get("name") or {}).get("ru") or not (s.get("name") or {}).get("en"):
            E("нужно имя на русском и английском")
        if not HEX.fullmatch(s.get("color", "")):
            E("цвет — #RRGGBB")
        if s.get("region") not in REGIONS:
            E(f"region — одно из {REGIONS} (регион страны оператора)")
        if s.get("type") not in STYPES:
            E(f"type — одно из {STYPES}")
        if not s.get("country") or not s.get("country_en"):
            E("нужны country и country_en — страна оператора")
        if s.get("bus") and s["bus"] not in BUS_TYPES:
            E(f"bus — одно из {BUS_TYPES} (схема 3D-модели по типу платформы)")
        mil = "Воен" in (s.get("category") or "") or "ilitary" in (s.get("category_en") or "")
        if mil and s.get("classification") != "gcat":
            E("военная система без classification: \"gcat\" (назначение официально не раскрывается)")
        if s.get("verifiedAt"):
            if not DATE.fullmatch(s["verifiedAt"]):
                E("verifiedAt — ГГГГ-ММ-ДД")
            srcs = s.get("descriptionSources") or []
            prim = [x for x in srcs if x.get("kind") == "primary"]
            doms = {urllib.parse.urlparse(x.get("url", "")).hostname for x in srcs if x.get("kind") == "secondary"}
            for x in srcs:
                if x.get("kind") not in ("primary", "secondary") or not re.match(r"https?://", x.get("url", "")) or not DATE.fullmatch(x.get("accessed", "")):
                    E(f"источник {x.get('title')!r}: нужны kind, http(s)-ссылка и accessed")
            if not prim and len(doms) < 2:
                E("описание без первичного источника или двух независимых вторичных")
            for k in ("description", "description_en", "operator_en", "category_en"):
                if not s.get(k):
                    E(f"нет поля {k}")
        else:
            legacy += 1
        body = B.get(s.get("dataKey", ""))
        if body is None:
            E(f"нет блока данных {s.get('dataKey')}")
            continue
        b = json.loads(body)
        if isinstance(b, dict) and b.get("src"):
            continue                       # блок вынесен в файл (updater) — проверяется в шаблоне
        if (s.get("select") or {}).get("satcatGroup"):
            if b.get("fields") != CATALOG_FIELDS:
                E("блок системы по SATCAT — не в формате каталога")
            elif b.get("rows") and not any(x.get("id", "").startswith("celestrak-satcat-") for x in b.get("sources", [])):
                E("у состава по SATCAT нет источника celestrak-satcat-*")
        if s.get("format") == "catalog":
            f = b.get("fields") or []
            if "norad" not in f or "elements" not in f:
                E("каталог без полей norad/elements")
                continue
            ix = {k: f.index(k) for k in ("norad", "name", "cospar", "launchDate", "epoch", "elements") if k in f}
            for r in b.get("rows", []):
                n = r[ix["norad"]]
                tag = f"{sid}/{n}"
                if not isinstance(n, int) or not 0 < n < 1_000_000:
                    err.append(f"{tag}: NORAD — целое 1..999999")
                elif n in seen:
                    err.append(f"{tag}: уже есть в системе {seen[n]}")
                else:
                    seen[n] = sid
                if not r[ix["name"]]:
                    err.append(f"{tag}: нет названия")
                if r[ix["cospar"]] and not COSPAR.fullmatch(r[ix["cospar"]]):
                    err.append(f"{tag}: COSPAR {r[ix['cospar']]!r} — формат ГГГГ-NNNA")
                if "launchDate" in ix and r[ix["launchDate"]] and not DATE.fullmatch(r[ix["launchDate"]]):
                    err.append(f"{tag}: дата запуска — ГГГГ-ММ-ДД")
                el = r[ix["elements"]]
                if not (isinstance(el, list) and ((el[:1] == ["T"] and len(el) == 3) or (el[:1] == ["O"] and len(el) == 11))):
                    err.append(f"{tag}: элементы орбиты — [\"T\", l1, l2] или [\"O\", 10 значений]")
        elif s.get("format") == "constellation":
            for x in b.get("satellites", []):
                n = x.get("noradId")
                if n in seen:
                    err.append(f"{sid}/{n}: уже есть в системе {seen[n]}")
                elif n is not None:
                    seen[n] = sid
    err += check_models(reg, seen, root)
    if legacy:
        warn.append(f"систем без verifiedAt (описания до введения правил источников): {legacy}")
    return err, warn


if __name__ == "__main__":
    args = sys.argv[1:]
    root = None
    if "--root" in args:
        k = args.index("--root"); root = args[k + 1]; del args[k:k + 2]
    if len(args) != 1:
        sys.exit("Использование: check_catalog.py <страница.html> [--root <корень сайта, где лежит models/>]")
    with open(args[0], encoding="utf-8") as f:
        errors, warnings = check(f.read(), root or os.path.dirname(os.path.abspath(args[0])))
    for w in warnings:
        print("предупреждение:", w)
    for e in errors:
        print("ОШИБКА:", e)
    print(f"каталог: {'ошибок нет' if not errors else f'ошибок {len(errors)}'}")
    sys.exit(1 if errors else 0)
