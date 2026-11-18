"""Variantes de composición: qué se repite de verdad en las 626 partidas de Abrams.

Diego preguntó si podemos tener «todas las variantes de oponentes y compañeros». Medido
sobre el banco real (`data/replay_cache.json`, 614 partidas usables):

- **la plantilla completa casi nunca se repite**: 612 composiciones enemigas distintas en
  614 partidas. El espacio teórico (5 aliados de 24 y 6 enemigos de 25) es de miles de
  millones, así que la plantilla exacta no sirve como unidad de memoria;
- **los pares sí se repiten**: 874 pares enemigos distintos, mediana 9 apariciones y 109
  pares con 20 o más. Ahí es donde hay muestra para decidir;
- los tríos existen (6 059 distintos) pero solo unos pocos pasan de 5 apariciones.

Por eso este módulo indexa en unidades de k héroes (2, 3 o la plantilla entera) y siempre
devuelve la muestra: un winrate de 2 partidas no es un patrón, es anécdota.
"""
from __future__ import annotations

import itertools
import json
import math
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANCO = os.path.join(RAIZ, "data", "replay_cache.json")
#: Muestra versionada de 60 partidas: lo único que hay en un clon limpio, porque el cache
#: completo (626 partidas, 8 MB) no se versiona. Sirve para que el panel y las pruebas
#: funcionen sin descargar nada, avisando de que es una muestra.
MUESTRA = os.path.join(RAIZ, "data", "replay_muestra.json")
ARCHIVO = os.path.join(RAIZ, "data", "archivo")
HEROES = os.path.join(RAIZ, "data", "heroes.json")

MIN_N = 5          # por debajo de esto no se enseña como patrón


def wilson(wins, losses, z=1.96):
    """Cota inferior del 95 %: castiga las rachas cortas en vez de premiarlas."""
    n = wins + losses
    if n <= 0:
        return 0.0
    p = wins / n
    return (p + z * z / (2 * n)
            - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def nombres():
    try:
        with open(HEROES, encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError):
        return {}
    return {int(k): v.get("nombre", str(k)) for k, v in crudo.items()}


def indice_por_nombre():
    """{'abrams': 6, ...} para que la CLI acepte nombres en vez de ids."""
    try:
        with open(os.path.join(RAIZ, "data", "heroes_index.json"), encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): int(v) for k, v in crudo.items()}


def _fecha(texto):
    """'2026-11-15 17:20:21' -> timestamp, o None si no se puede."""
    import datetime as dt
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(texto)[:19], formato).timestamp()
        except (TypeError, ValueError):
            continue
    return None


def cargar_archivo(carpeta=None, dias=None, heroe=6):
    """Todas las partidas del archivo local (JSONL comprimido), normalizadas.

    El archivo lo llena `herramientas/archivo_abrams.py` con el endpoint en bloque:
    miles de partidas de Abrams con héroes, equipos, KDA y net worth. Mismo esquema que
    el banco, así que se indexa con las mismas funciones.
    """
    import glob
    import gzip
    partidas = []
    for ruta in sorted(glob.glob(os.path.join(carpeta or ARCHIVO, "*.jsonl.gz"))):
        # El archivo puede estar creciendo mientras se lee (una descarga en curso):
        # se aprovechan las líneas completas y se corta en la primera incompleta.
        crudo = []
        try:
            with gzip.open(ruta, "rt", encoding="utf-8") as f:
                for linea in f:
                    if not linea.strip():
                        continue
                    try:
                        crudo.append(json.loads(linea))
                    except ValueError:
                        break
        except (OSError, EOFError, ValueError):
            pass
        if not crudo:
            continue
        # El archivo puede tener varios héroes (heroe-<id>-items-*.jsonl.gz). Sin este
        # filtro se mezclaban las partidas de Abrams con las de Haze y el «banco» pasaba
        # de 166k a 179k sin que nadie hubiera jugado nada: visto el 2026-11-15 al añadir
        # el segundo héroe.
        crudo = [p for p in crudo
                 if int(p.get("heroe", 6)) == int(heroe)] if isinstance(crudo, list) else []
        normalizadas = cargar_preparado(crudo)
        if dias:
            limite = __import__("time").time() - dias * 86400
            crudo_por_id = {p.get("match_id"): p for p in crudo if isinstance(p, dict)}
            normalizadas = [
                p for p in normalizadas
                if (_fecha((crudo_por_id.get(p["match_id"]) or {}).get("start_time"))
                    or 0) >= limite]
        partidas.extend(normalizadas)
    return partidas


def cargar(ruta=None):
    """Partidas del banco; si no está el completo, la muestra versionada.

    Un clon limpio no trae `replay_cache.json` (8 MB, fuera de git). Antes eso dejaba el
    índice y las pruebas vacías sin explicar por qué; ahora se cae a la muestra de 60 y
    quien la use puede mirar `fuente_banco()` para saber qué está leyendo.
    """
    for candidata in ([ruta] if ruta else [BANCO, MUESTRA]):
        try:
            with open(candidata, encoding="utf-8") as f:
                return cargar_preparado(json.load(f))
        except (OSError, ValueError, TypeError):
            continue
    return []


def fuente_banco():
    """Ruta del archivo que se está usando, o None."""
    for candidata in (BANCO, MUESTRA):
        if os.path.exists(candidata):
            return candidata
    return None


def _equipo(valor):
    """0/1 desde int, "Team0"/"Team1" o lo que mande la fuente.

    El archivo en bloque del API trae los equipos como texto ("Team0"), el banco local
    como entero. Se acepta lo que venga: una variante mal tipada no es una variante.
    """
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, int):
        return valor
    texto = str(valor or "").strip()
    if texto.isdigit():
        return int(texto)
    return 0 if texto.lower().endswith("0") else 1


def cargar_preparado(crudo):
    """Normaliza una lista de partidas crudas (banco o cualquier fuente con el esquema).

    Se descartan las que no traen 5 aliados y 6 enemigos con héroe: sin composición no
    hay variante que contar. El «yo» nunca entra en las listas.
    """
    partidas = []
    for e in crudo if isinstance(crudo, list) else []:
        try:
            yo = e["yo"]
            equipo, slot = _equipo(yo["team"]), int(yo["slot"])
            jugadores = [j for j in e["jugadores"] if j.get("hero") is not None]
        except (KeyError, TypeError, ValueError):
            continue
        if len(jugadores) < 12:
            continue
        aliados = tuple(sorted(j["hero"] for j in jugadores
                               if _equipo(j["team"]) == equipo and j["slot"] != slot))
        enemigos = tuple(sorted(j["hero"] for j in jugadores
                                if _equipo(j["team"]) != equipo))
        if len(aliados) != 5 or len(enemigos) != 6:
            continue
        partidas.append({"match_id": e.get("match_id"), "aliados": aliados,
                         "enemigos": enemigos, "gano": bool(e.get("gane")),
                         "duracion_s": e.get("duracion_s")})
    return partidas


def _acumular(cubos, clave, gano):
    cubo = cubos.setdefault(clave, [0, 0])
    cubo[0] += 1
    cubo[1] += int(bool(gano))


def construir(partidas, k=2):
    """Índices de composiciones en unidades de `k` héroes.

    k=2 pares, k=3 tríos, k=6 la plantilla enemiga completa, k=5 la aliada.
    Devuelve {'enemigos': {clave: [n, victorias]}, 'aliados': {...},
             'partidas': n, 'victorias': n}.
    """
    enem, ali = {}, {}
    victorias = 0
    for p in partidas:
        victorias += int(p["gano"])
        for combo in set(itertools.combinations(p["enemigos"], min(k, len(p["enemigos"])))):
            _acumular(enem, combo, p["gano"])
        for combo in set(itertools.combinations(p["aliados"], min(k, len(p["aliados"])))):
            _acumular(ali, combo, p["gano"])
    return {"enemigos": enem, "aliados": ali, "k": k,
            "partidas": len(partidas), "victorias": victorias}


def listar(indice, min_n=MIN_N, orden="cota"):
    """Patrones con muestra suficiente, ordenados por cota inferior de winrate.

    `orden='cota'` (por defecto) saca lo que gana; `orden='frecuencia'` saca lo común.
    """
    filas = []
    for combo, (n, wins) in indice.get("enemigos", {}).items():
        if n < min_n:
            continue
        filas.append({"combo": combo, "n": n, "wins": wins,
                      "wr": wins / n, "lb": wilson(wins, n - wins)})
    if orden == "frecuencia":
        filas.sort(key=lambda f: (-f["n"], -f["lb"]))
    elif orden == "peor":
        filas.sort(key=lambda f: (f["lb"], -f["n"]))
    else:
        filas.sort(key=lambda f: (-f["lb"], -f["n"]))
    return filas


def consultar(indice, enemigos=None, aliados=None, min_n=MIN_N):
    """Patrones que contienen a esos héroes. Devuelve lo que se repite, no una promesa.

    Si la muestra no llega, la lista sale vacía y el llamador debe decir «no hay datos»
    en vez de un porcentaje.
    """
    enemigos = set(enemigos or [])
    aliados = set(aliados or [])
    salida = {"enemigos": [], "aliados": []}
    for combo, (n, wins) in (indice.get("enemigos") or {}).items():
        if n < min_n or not enemigos.issubset(combo):
            continue
        salida["enemigos"].append({"combo": combo, "n": n, "wr": wins / n,
                                   "lb": wilson(wins, n - wins)})
    for combo, (n, wins) in (indice.get("aliados") or {}).items():
        if n < min_n or not aliados.issubset(combo):
            continue
        salida["aliados"].append({"combo": combo, "n": n, "wr": wins / n,
                                  "lb": wilson(wins, n - wins)})
    for clave in ("enemigos", "aliados"):
        salida[clave].sort(key=lambda f: (-f["lb"], -f["n"]))
    return salida


def resumen(partidas, indices):
    """Los números que contestan «¿de verdad nos toca siempre lo mismo?»."""
    comps = {}
    for p in partidas:
        comps[p["enemigos"]] = comps.get(p["enemigos"], 0) + 1
    repetidas = {c: n for c, n in comps.items() if n > 1}
    pares = indices.get("enemigos") or {}
    con_muestra = [n for n in pares.values() if n[0] >= MIN_N]
    return {
        "partidas": len(partidas),
        "comps_enemigas_distintas": len(comps),
        "comps_repetidas": len(repetidas),
        "partidas_en_comp_repetida": sum(repetidas.values()),
        "pares_distintos": len(pares),
        "pares_con_muestra": len(con_muestra),
        "pares_mediana": (sorted(n[0] for n in pares.values())[len(pares) // 2]
                          if pares else 0),
    }
