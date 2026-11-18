"""Histórico de composiciones: «esta comp ya la jugaste, así te fue».

El archivo local (`data/archivo/*.jsonl.gz`) tiene decenas de miles de partidas de Abrams
con los 12 héroes. Este módulo lo convierte en dos índices pequeños —plantilla completa y
pares de enemigos— y responde una única pregunta útil en partida:

    con estos seis enemigos, ¿qué se ha visto antes y cómo terminó?

Por qué pares y no plantilla: medido sobre 36 902 partidas recientes, hay 33 764
plantillas enemigas distintas y la que más se repite sale 9 veces. Los pares, en cambio,
tienen mediana 499 apariciones. La plantilla se informa si existe, sin adornarla.

El índice se guarda en disco (`data/historico.json.gz`) y se relee al arrancar: construir
desde cero 37 000 partidas son ~2 s, y el coach no puede pagarlos en cada lectura del HUD.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import time

from . import variantes

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO = os.path.join(RAIZ, "data", "historico.json.gz")
MIN_N = 100        # muestra mínima para afirmar algo de un par en partida


def wilson(wins, losses, z=1.96):
    n = wins + losses
    if n <= 0:
        return 0.0
    p = wins / n
    return (p + z * z / (2 * n)
            - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def nombre_a_id():
    """{'haze': 13, 'mo & krill': 18, ...} desde data/heroes.json."""
    try:
        with open(os.path.join(RAIZ, "data", "heroes.json"), encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError):
        return {}
    salida = {}
    for clave, info in crudo.items():
        nombre = str(info.get("nombre") or "").strip().lower()
        if not nombre:
            continue
        salida[nombre] = int(clave)
        # El mismo héroe se escribe «Rat King», «rat_king» o «ratking» según la fuente.
        salida[nombre.replace(" ", "_")] = int(clave)
        salida[nombre.replace(" ", "")] = int(clave)
        salida[nombre.replace(" ", "_").replace("&", "and")] = int(clave)
    # Y los slugs curados del índice, que traen los nombres raros («mo_&_krill»).
    try:
        with open(os.path.join(RAIZ, "data", "heroes_index.json"), encoding="utf-8") as f:
            for slug, hid in json.load(f).items():
                salida.setdefault(str(slug).strip().lower(), int(hid))
    except (OSError, ValueError, TypeError):
        pass
    return salida


def nombres():
    """{13: 'Haze', ...} para que el aviso diga héroes y no ids."""
    try:
        with open(os.path.join(RAIZ, "data", "heroes.json"), encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError):
        return {}
    return {int(k): v.get("nombre", str(k)) for k, v in crudo.items()}


def _nombres_de(combo, tabla):
    return "+".join(tabla.get(int(h), str(h)) for h in combo)


def construir(partidas):
    """Índices de plantilla completa y pares a partir de partidas normalizadas."""
    comp, pares, aliados = {}, {}, {}
    victorias = 0
    desde = hasta = None
    for p in partidas:
        victorias += int(p["gano"])
        clave = ",".join(str(h) for h in p["enemigos"])
        _sumar(comp, clave, p["gano"])
        for a, b in _pares(p["enemigos"]):
            _sumar(pares, f"{a},{b}", p["gano"])
        for a, b in _pares(p["aliados"]):
            _sumar(aliados, f"{a},{b}", p["gano"])
    return {"total": len(partidas), "victorias": victorias,
            "comp": comp, "pares": pares, "aliados": aliados,
            "generado": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "desde": desde, "hasta": hasta}


def _sumar(cubo, clave, gano):
    fila = cubo.setdefault(clave, [0, 0])
    fila[0] += 1
    fila[1] += int(bool(gano))


def _pares(heroes):
    heroes = list(heroes)
    for i in range(len(heroes)):
        for j in range(i + 1, len(heroes)):
            a, b = sorted((heroes[i], heroes[j]))
            yield a, b


def construir_desde_archivo(dias=0, carpeta=None):
    partidas = variantes.cargar_archivo(carpeta=carpeta, dias=dias)
    return construir(partidas)


def guardar(indice, ruta=None):
    ruta = ruta or ARCHIVO
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = ruta + ".tmp"
    with gzip.open(temporal, "wt", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False)
    os.replace(temporal, ruta)
    return ruta


def cargar(ruta=None):
    ruta = ruta or ARCHIVO
    try:
        with gzip.open(ruta, "rt", encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError, EOFError):
        return None
    return datos if isinstance(datos, dict) else None


_CACHE = {"indice": None, "ts": 0.0}


def indice(max_edad_s=3600.0):
    """El índice en memoria, releyendo como mucho una vez por hora."""
    ahora = time.time()
    if _CACHE["indice"] is None or ahora - _CACHE["ts"] > max_edad_s:
        _CACHE["indice"] = cargar() or {"total": 0, "comp": {}, "pares": {}}
        _CACHE["ts"] = ahora
    return _CACHE["indice"]


def consultar(indice_datos, enemigos, min_n=MIN_N, pares_que_enseñar=3):
    """Lo que el histórico puede decir de esta composición enemiga, o nada.

    `enemigos` son ids (o nombres, se traducen). Devuelve:
        {'comp': {...}|None, 'pares': [...], 'aviso': str, 'total': n}
    """
    traduccion = nombre_a_id()
    ids = []
    for h in enemigos or []:
        if isinstance(h, int):
            ids.append(h)
            continue
        texto = str(h).strip().lower()
        if texto.isdigit():
            ids.append(int(texto))
        elif texto in traduccion:
            ids.append(traduccion[texto])
    ids = sorted(set(ids))
    if len(ids) < 2 or not indice_datos:
        return {"comp": None, "pares": [], "aviso": "", "total": 0}

    total_partidas = int(indice_datos.get("total") or 0)
    comp = None
    if len(ids) == 6:
        fila = (indice_datos.get("comp") or {}).get(",".join(str(h) for h in ids))
        if fila:
            n, wins = fila
            comp = {"n": n, "wr": wins / n, "lb": wilson(wins, n - wins)}

    pares = []
    for clave, (n, wins) in (indice_datos.get("pares") or {}).items():
        try:
            a, b = (int(x) for x in str(clave).split(","))
        except (ValueError, TypeError):
            continue
        if a not in ids or b not in ids or n < min_n:
            continue
        pares.append({"combo": (a, b), "n": n, "wr": wins / n,
                      "lb": wilson(wins, n - wins)})
    pares.sort(key=lambda f: (f["lb"], -f["n"]))
    elegidos = pares[:pares_que_enseñar]

    partes = []
    if comp:
        partes.append(f"esta comp la viste {comp['n']} vez"
                      f"{'es' if comp['n'] > 1 else ''} (ganaste {comp['wr']:.0%})")
    if elegidos:
        peor = elegidos[0]
        tabla = nombres()
        partes.append(f"peor par {_nombres_de(peor['combo'], tabla)} "
                      f"{peor['wr']:.0%} en {peor['n']}")
    aviso = " · ".join(partes)
    return {"comp": comp, "pares": elegidos, "aviso": aviso,
            "total": total_partidas, "muestra_par": elegidos[0]["n"] if elegidos else 0}


def para_panel(enemigos, indice_datos=None):
    """Atajo que usa el bucle en vivo: nunca lanza, devuelve {} si no hay nada."""
    try:
        datos = indice_datos if indice_datos is not None else indice()
        salida = consultar(datos, enemigos)
        return salida if salida.get("aviso") else {}
    except Exception:                                          # noqa: BLE001
        return {}
