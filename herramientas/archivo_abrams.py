#!/usr/bin/env python3
"""Archivo local de partidas de Abrams: todas las que el API público puede dar.

Hallazgo del 2026-11-15 (medido, no supuesto): `GET /v1/matches/metadata` acepta
`hero_ids`, ventana por `min_match_id`/`max_match_id`, `limit=1000` y `format` — con
ventanas de 500 000 ids devuelve **1000 partidas de Abrams en ~1.5 s y 4.5 MB**. Sin
ventana superior la consulta se cae (504) porque escanea la tabla entera, así que se
recorre el espacio de ids a saltos acotados y se pagina dentro de cada uno.

Para qué sirve: el banco de `replay_cache.json` son 626 partidas. Con esto se puede tener
el archivo completo de Abrams —decenas o cientos de miles— y con eso la pregunta de las
«variantes» cambia de escala: los pares dejan de tener 9 casos y pasan a tener cientos.

Formato de salida: JSONL comprimido, un objeto por partida, con el mismo esquema que el
banco (`yo`, `jugadores`, `gane`) para que `coach.variantes` lo lea sin adaptadores.

    python3 herramientas/archivo_abrams.py --objetivo 5000
    python3 herramientas/archivo_abrams.py --desde 13000000 --hasta 14000000
    python3 herramientas/archivo_abrams.py --objetivo 200000 --ventana 500000

Se puede reanudar: el estado vive en `data/archivo/estado.json` y nunca se reescribe lo
ya bajado.
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
CARPETA = os.path.join(RAIZ, "data", "archivo")
ESTADO = os.path.join(CARPETA, "estado.json")
API = "https://api.deadlock-api.com/v1/matches/metadata"
CABECERAS = {"User-Agent": "abrams-coach/1.0 (archivo de Abrams)",
             "Accept": "application/json"}
HEROE = 6                      # Abrams (por defecto; --heroe lo cambia)
LIMITE = 1000                  # máximo por petición que acepta el endpoint
PAUSA_S = 0.7                  # cortesía entre peticiones


def _estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("siguiente_id", 1)
    d.setdefault("bajadas", 0)
    d.setdefault("peticiones", 0)
    d.setdefault("fallos", 0)
    return d


def _guardar_estado(d):
    os.makedirs(CARPETA, exist_ok=True)
    temporal = ESTADO + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(temporal, ESTADO)


def _pedir(desde, hasta, timeout=180.0, atras=False, con_items=False, limite=LIMITE,
           heroe=HEROE):
    """Partidas de Abrams en esa ventana de ids, o None si la API no contesta."""
    params = {"hero_ids": str(heroe), "min_match_id": int(desde),
              "max_match_id": int(hasta), "limit": int(limite),
              "order_by": "match_id",
              "order_direction": "desc" if atras else "asc",
              "include_info": "true", "include_player_info": "true",
              "include_player_items": "true" if con_items else "false",
              "include_player_stats": "false",
              "include_player_final_stats": "false"}
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=CABECERAS),
                                    timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:                                          # noqa: BLE001
        return None


def _equipo(valor):
    """0/1 desde int o "Team0"/"Team1": el endpoint en bloque manda texto."""
    if isinstance(valor, int):
        return valor
    texto = str(valor or "")
    return 0 if texto.endswith("0") else 1


def _items_de(partida, slot):
    """Compras de un jugador concreto, en el formato mínimo (id, segundo, vendido)."""
    for j in ((partida.get("match_info") or partida).get("players") or []):
        if j.get("player_slot") == slot:
            filas = []
            for it in (j.get("items") or []):
                try:
                    filas.append([int(it.get("item_id")), int(it.get("game_time_s") or 0),
                                  int(it.get("sold_time_s") or 0)])
                except (TypeError, ValueError):
                    continue
            return filas
    return []


def _recortar(partida, con_items=False, heroe=HEROE):
    """Lo que hace falta para variantes y decisiones; el resto se descarta.

    Guardar el metadata entero son ~4.5 kB por partida y aquí sobran tres cuartas partes:
    posiciones, muertes detalladas y estadísticas cada tres minutos.
    """
    try:
        info = partida.get("match_info") or partida
        jugadores = info.get("players") or []
        if len(jugadores) < 12:
            return None
        filas = []
        yo = None
        for j in jugadores:
            fila = {"slot": j.get("player_slot"), "team": _equipo(j.get("team")),
                    "hero": j.get("hero_id"), "kills": j.get("kills"),
                    "deaths": j.get("deaths"), "assists": j.get("assists"),
                    "neto": j.get("net_worth")}
            filas.append(fila)
            if fila["hero"] == heroe and yo is None:
                yo = {"slot": fila["slot"], "team": fila["team"], "hero": heroe}
        if yo is None:                       # el filtro dice ese héroe pero no aparece
            return None
        gane = _equipo(info.get("winning_team")) if info.get("winning_team") is not None else None
        salida = {"match_id": info.get("match_id") or partida.get("match_id"),
                "heroe": heroe,
                "start_time": info.get("start_time"),
                "duracion_s": info.get("duration_s"),
                "gane": (gane == yo["team"]) if gane is not None else None,
                "yo": yo, "jugadores": filas}
        if con_items:
            salida["items"] = _items_de(partida, yo["slot"])
        return salida
    except (AttributeError, TypeError, KeyError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objetivo", type=int, default=5000,
                    help="cuántas partidas nuevas bajar en esta corrida")
    ap.add_argument("--desde", type=int, default=None,
                    help="id de partida (o tope, con --atras)")
    ap.add_argument("--hasta", type=int, default=None,
                    help="id final (o piso, con --atras)")
    ap.add_argument("--heroe", default=str(HEROE),
                    help="héroe a archivar: id o nombre (abrams, haze, kelvin...)")
    ap.add_argument("--atras", action="store_true",
                    help="barrer hacia atrás desde --desde: lo más nuevo primero")
    ap.add_argument("--ventana", type=int, default=500_000,
                    help="ids por petición (medido: 500k da 1000 partidas en ~1.5 s)")
    ap.add_argument("--con-items", action="store_true",
                    help="guardar también las compras del Abrams (archivo aparte, ~98 kB "
                         "por partida descargados)")
    ap.add_argument("--limite", type=int, default=LIMITE,
                    help="partidas por petición (bajar con --con-items: cada partida trae "
                         "más datos)")
    ap.add_argument("--max-peticiones", type=int, default=0,
                    help="corta después de N peticiones (0 = sin tope)")
    a = ap.parse_args()

    est = _estado()
    os.makedirs(CARPETA, exist_ok=True)
    if a.atras:
        arriba = a.desde if a.desde is not None else est.get("siguiente_id", 1)
        abajo = a.hasta if a.hasta is not None else max(1, arriba - a.ventana * 400)
    else:
        abajo = a.desde if a.desde is not None else est["siguiente_id"]
        arriba = a.hasta if a.hasta is not None else abajo + a.ventana * 400

    # Un archivo por corrida: si dos descargas coinciden o alguien está leyendo, no se
    # pisa un .gz que ya está abierto (añadir a gzip deja el stream truncado para otros).
    from coach import historico as _H
    heroe = int(a.heroe) if str(a.heroe).isdigit() else _H.nombre_a_id().get(
        str(a.heroe).strip().lower(), HEROE)
    sufijo = "items-" if a.con_items else ""
    ruta = os.path.join(CARPETA, f"heroe-{heroe}-{sufijo}{time.strftime('%Y-%m-%d-%H%M')}.jsonl.gz")
    nuevas = peticiones = 0
    t0 = time.time()
    cursor = abajo
    tope = arriba

    with gzip.open(ruta, "at", encoding="utf-8") as salida:
        while nuevas < a.objetivo:
            if a.max_peticiones and peticiones >= a.max_peticiones:
                break
            if a.atras:
                if tope - cursor <= 0:
                    break
                fin = tope
                ini = max(cursor, tope - a.ventana)
            else:
                if cursor >= tope:
                    break
                ini = cursor
                fin = min(cursor + max(1, a.ventana), tope)

            datos = _pedir(ini, fin, atras=a.atras, con_items=a.con_items,
                           limite=a.limite, heroe=heroe)
            peticiones += 1
            if not datos:
                est["fallos"] += 1
                if a.atras:
                    tope = ini
                else:
                    cursor = fin
                print(f"  {ini:>11} sin datos · fallos {est['fallos']}", flush=True)
                time.sleep(PAUSA_S)
                if est["fallos"] >= 6:
                    print("demasiados fallos seguidos: paro")
                    break
                continue

            for bruto in datos:
                p = _recortar(bruto, con_items=a.con_items, heroe=heroe)
                if not p:
                    continue
                salida.write(json.dumps(p, ensure_ascii=False) + "\n")
                nuevas += 1
                est["bajadas"] += 1

            ids = [m.get("match_id") or 0 for m in datos]
            primero, ultimo = min(ids), max(ids)
            print(f"  ventana {ini:>11}..{fin:<11} · {len(datos):4} partidas · +{nuevas}"
                  f" · ids {primero}..{ultimo}", flush=True)

            # La ventana llena significa que hay más partidas dentro: se pagina por id
            # en vez de saltar la ventana entera y perderlas.
            if len(datos) >= a.limite and ultimo:
                if a.atras:
                    tope = primero - 1
                else:
                    cursor = ultimo + 1
            else:
                if a.atras:
                    tope = ini
                else:
                    cursor = fin
            time.sleep(PAUSA_S)

    est["siguiente_id"] = tope if a.atras else cursor
    est["peticiones"] += peticiones
    _guardar_estado(est)
    seg = time.time() - t0
    print(f"\n{nuevas} partidas nuevas en {seg:.1f} s · {peticiones} peticiones · "
          f"{os.path.getsize(ruta)/1024/1024:.1f} MB en {os.path.relpath(ruta, RAIZ)}")
    print(f"estado: cursor en {est['siguiente_id']} · total acumulado {est['bajadas']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
