"""Qué compra el Abrams que gana contra cada composición enemiga.

Fuente: `data/archivo/abrams-items-*.jsonl.gz` (lo llena `herramientas/archivo_abrams.py`
con `--con-items`). Cada partida trae la composición enemiga, el resultado y **las compras
del Abrams con su segundo**, sacadas del archivo público de partidas.

Qué responde: «contra Graves + Rat King, ¿qué compran los que ganan?». Es la pregunta que
el banco de 626 partidas no podía contestar con muestra y que los agregados del API no
contestan porque no cruzan ítem × composición.

Lo que NO hace: decir que un ítem gana. El winrate por ítem está sesgado por selección
—se compra para responder a lo que ya está pasando— así que se exige muestra, se compara
contra el winrate base de esa misma composición y se publica la cota inferior. La lectura
correcta es «este ítem aparece en las partidas que ganan», no «comprar esto te hace ganar».
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import os
import statistics

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO = os.path.join(RAIZ, "data", "archivo")
MIN_N = 100


def wilson(wins, losses, z=1.96):
    n = wins + losses
    if n <= 0:
        return 0.0
    p = wins / n
    return (p + z * z / (2 * n)
            - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def _gano(p):
    """El resultado, venga como «gano» (normalizado) o «gane» (crudo del archivo).

    El archivo guarda `gane` y `coach.variantes` normaliza a `gano`; aquí se aceptan los
    dos porque este módulo lee el archivo directamente y no pasa por esa capa.
    """
    valor = p.get("gano", p.get("gane"))
    return bool(valor) if valor is not None else None


def cargar(carpeta=None, heroe=6):
    """Partidas con compras de ese héroe (Abrams por defecto).

    El archivo ahora puede tener varios héroes (`heroe-<id>-items-*.jsonl.gz`). Antes este
    cargador se tragaba todos los `*items-*` y habría mezclado las compras de Haze con las
    de Abrams sin avisar. Los archivos viejos no traen el campo: cuentan como Abrams.
    """
    partidas = []
    for ruta in sorted(glob.glob(os.path.join(carpeta or ARCHIVO, "*items-*.jsonl.gz"))):
        try:
            with gzip.open(ruta, "rt", encoding="utf-8") as f:
                for linea in f:
                    if not linea.strip():
                        continue
                    try:
                        p = json.loads(linea)
                    except ValueError:
                        break
                    if not p.get("items") or _gano(p) is None:
                        continue
                    if int(p.get("heroe", 6)) != int(heroe):
                        continue
                    partidas.append(p)
        except (OSError, EOFError, ValueError):
            continue
    return partidas


def enemigos_de(partida):
    """Ids de los seis enemigos, deducidos del equipo del Abrams."""
    yo = partida.get("yo") or {}
    equipo = yo.get("team")
    ids = sorted({j.get("hero") for j in (partida.get("jugadores") or [])
                  if j.get("team") != equipo and j.get("hero") is not None})
    return tuple(ids)


def filtrar(partidas, enemigos=None):
    """Partidas cuya composición enemiga contiene a esos héroes (todos)."""
    if not enemigos:
        return partidas
    buscados = set(enemigos)
    return [p for p in partidas if buscados.issubset(set(enemigos_de(p)))]


def por_item(partidas, min_n=MIN_N, catalogo=None):
    """Winrate de cada ítem entre estas partidas, con su cota y su momento de compra.

    Devuelve {'n_partidas', 'base', 'items': [...]} ordenado por cota inferior.
    """
    catalogo = catalogo if catalogo is not None else _catalogo()
    total = len(partidas)
    if not total:
        return {"n_partidas": 0, "base": 0.0, "items": []}
    base = sum(1 for p in partidas if _gano(p)) / total
    acumulado = {}
    from .fuentes import items_assets
    tipos = items_assets.cargar()
    for p in partidas:
        vistos = {}
        for fila in p.get("items") or []:
            try:
                iid, t = int(fila[0]), int(fila[1])
            except (IndexError, TypeError, ValueError):
                continue
            if not items_assets.es_item(iid, tipos):
                continue
            if iid not in vistos or t < vistos[iid]:
                vistos[iid] = t
        for iid, t in vistos.items():
            cubo = acumulado.setdefault(iid, {"n": 0, "wins": 0, "tiempos": []})
            cubo["n"] += 1
            cubo["wins"] += int(bool(_gano(p)))
            cubo["tiempos"].append(t)
    items = []
    for iid, cubo in acumulado.items():
        n = cubo["n"]
        if n < min_n:
            continue
        info = catalogo.get(str(iid)) or {}
        items.append({"id": iid, "nombre": info.get("nombre") or str(iid),
                      "costo": info.get("costo"), "n": n,
                      "wr": cubo["wins"] / n,
                      "lb": wilson(cubo["wins"], n - cubo["wins"]),
                      "t_mediana_s": int(statistics.median(cubo["tiempos"]))})
    items.sort(key=lambda f: (-f["lb"], -f["n"]))
    return {"n_partidas": total, "base": base, "items": items}


def comparar(partidas, enemigos=None, min_n=MIN_N, catalogo=None):
    """Tabla de ítems para una composición, con la base de esa misma composición."""
    sub = filtrar(partidas, enemigos)
    tabla = por_item(sub, min_n=min_n, catalogo=catalogo)
    tabla["enemigos"] = list(enemigos or [])
    tabla["base_global"] = (sum(1 for p in partidas if _gano(p)) / len(partidas)
                            if partidas else 0.0)
    return tabla


TABLA_HEROES = os.path.join(RAIZ, "data", "items_por_heroe.json")


def por_heroe(partidas, min_n=300, catalogo=None, heroes=None):
    """Tabla de ítems por héroe enemigo: lo que aparece en las partidas que se ganan.

    Se prefiere por héroe y no por composición porque una comp concreta de 6 héroes sale
    pocas veces, pero «contra Graves» tiene miles de partidas. En partida, el panel mira
    los seis enemigos y se queda con el ítem que coincide en varios.
    """
    catalogo = catalogo if catalogo is not None else _catalogo()
    tabla = {}
    for h in (heroes if heroes is not None else sorted({e for p in partidas
                                                        for e in enemigos_de(p)})):
        sub = [p for p in partidas if h in enemigos_de(p)]
        if not sub:
            continue
        datos = por_item(sub, min_n=min_n, catalogo=catalogo)
        if not datos["items"]:
            continue
        tabla[str(h)] = {"n": datos["n_partidas"], "base": round(datos["base"], 4),
                         "items": [{"id": f["id"], "nombre": f["nombre"], "n": f["n"],
                                    "wr": round(f["wr"], 4), "lb": round(f["lb"], 4),
                                    "t_s": f["t_mediana_s"]}
                                   for f in datos["items"][:12]]}
    return tabla


def guardar_por_heroe(tabla, ruta=None):
    ruta = ruta or TABLA_HEROES
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump({"generado": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                   "heroes": tabla}, f, ensure_ascii=False, indent=1)
    os.replace(temporal, ruta)
    return ruta


_TABLA = {"datos": None, "ts": 0.0}


def tabla_heroes(max_edad_s=3600.0):
    """La tabla guardada, releída como mucho una vez por hora. Nunca lanza."""
    import time
    ahora = time.time()
    if _TABLA["datos"] is None or ahora - _TABLA["ts"] > max_edad_s:
        try:
            with open(TABLA_HEROES, encoding="utf-8") as f:
                _TABLA["datos"] = (json.load(f) or {}).get("heroes") or {}
        except (OSError, ValueError):
            _TABLA["datos"] = {}
        _TABLA["ts"] = ahora
    return _TABLA["datos"]


def sugerencias(enemigos, min_heroes=2, top=3, min_n=300, min_pp=3.0):
    """Ítems que coinciden en varios enemigos y ganan de verdad contra su base.

    Tres filtros, porque con seis enemigos y una docena de ítems por héroe es fácil que
    algo «destaque» por azar:

    1. el ítem tiene que aparecer con muestra suficiente en **cada** héroe que lo aporta;
    2. tiene que superar la base de **su** héroe en `min_pp` puntos (no contra una base
       global, que era el error que inflaba el número a +20 pp);
    3. tiene que coincidir en `min_heroes` enemigos o más. Con uno solo, se calla.

    El delta que se publica es la media ponderada por muestra de los aportes, no el mejor
    caso: lo que se enseña tiene que poder sostenerse con todos los datos, no con el que
    más conviene.
    """
    tabla = tabla_heroes()
    cuenta = {}
    for h in enemigos or []:
        fila = tabla.get(str(h))
        if not fila:
            continue
        base_h = float(fila.get("base") or 0.0)
        for it in fila.get("items") or []:
            if it.get("n", 0) < min_n or not base_h:
                continue
            # Redondeado: (0.48 - 0.45) * 100 da 2.9999999999999973, y ese ruido dejaba
            # fuera un ítem que cumple justo el umbral.
            delta_pp = round((float(it.get("wr") or 0.0) - base_h) * 100, 6)
            if delta_pp < min_pp:
                continue
            cubo = cuenta.setdefault(it["id"], {"id": it["id"], "nombre": it["nombre"],
                                                "veces": 0, "peso": 0, "acum": 0.0,
                                                "n": 0, "wr": 0.0, "delta_pp": 0.0})
            cubo["veces"] += 1
            cubo["peso"] += int(it["n"])
            cubo["acum"] += delta_pp * int(it["n"])
            if int(it["n"]) > cubo["n"]:
                cubo["n"] = int(it["n"])
                cubo["wr"] = float(it.get("wr") or 0.0)
    elegidos = [c for c in cuenta.values() if c["veces"] >= min_heroes]
    for c in elegidos:
        c["delta_pp"] = c["acum"] / c["peso"] if c["peso"] else 0.0
    elegidos.sort(key=lambda c: (-c["veces"], -c["delta_pp"], -c["n"]))
    return elegidos[:top]


def texto_sugerencia(enemigos, min_heroes=2, top=3):
    """Una línea para el panel, o '' si no hay con qué sostenerla."""
    lista = sugerencias(enemigos, min_heroes=min_heroes, top=top)
    if not lista:
        return ""
    partes = []
    for c in lista:
        partes.append(f"{c['nombre']} {c['delta_pp']:+.0f}pp "
                      f"(n={c['n']}, {c['wr']:.0%})")
    return "contra esta comp, los que ganan compran: " + " · ".join(partes)


def _catalogo():
    try:
        with open(os.path.join(RAIZ, "data", "catalogo.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
