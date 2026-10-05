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
- аппарат: NORAD 1..999999 без повторов между системами, COSPAR ГГГГ-NNNA, даты ISO, элементы орбиты TLE или OMM.
"""
import json, re, sys, urllib.parse

CATALOG_FIELDS = ["norad", "name", "cospar", "launchDate", "gcatProgram", "gcatCategory", "subtype",
                  "satcat[perigee,apogee,inc,period,ops,owner]", "elementsSource", "epoch", "elements"]
COSPAR = re.compile(r"\d{4}-\d{3}[A-Z]{1,3}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def blocks(page):
    out = {}
    for m in re.finditer(r'<script type="application/json" id="([^"]+)">(.*?)</script>', page, re.S):
        if m.group(1) not in out:          # первый — настоящий блок; дальше в коде бывают примеры разметки
            out[m.group(1)] = m.group(2)
    return out


def check(page):
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
    if legacy:
        warn.append(f"систем без verifiedAt (описания до введения правил источников): {legacy}")
    return err, warn


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Использование: check_catalog.py <страница.html>")
    with open(sys.argv[1], encoding="utf-8") as f:
        errors, warnings = check(f.read())
    for w in warnings:
        print("предупреждение:", w)
    for e in errors:
        print("ОШИБКА:", e)
    print(f"каталог: {'ошибок нет' if not errors else f'ошибок {len(errors)}'}")
    sys.exit(1 if errors else 0)
