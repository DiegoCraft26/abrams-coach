#!/usr/bin/env python3
"""Prueba la vía SIN visión: conseguir tu partida y leerla por HTTP.

Qué hace, en este orden y sin tocar el juego:

1. **match id** — de `--match`, o del `console.log` del juego (gratis, sin red), o de
   `GET /v1/matches/active?account_id=<tu cuenta>`.
2. **URL del TV** — `GET /v1/matches/{id}/live/url`. Cuesta 1 de los 6 espectáculos por
   hora sin API key; queda cacheada 1 h por partida.
3. **una consulta de 5 s** al stream SSE: las 12 filas de jugador con almas, oro, KDA,
   héroe, equipo e ítems.

Comparado con el camino de píxeles: no depende del font del juego, no necesita que
nadie abra la tienda ni el marcador, y el reloj sale del tick (tick/64) en vez de OCR.

Uso:
    python3 herramientas/probar_vivo.py
    python3 herramientas/probar_vivo.py --match 134651996
    python3 herramientas/probar_vivo.py --url http://dist1-ord1.steamcontent.com/tv/...
    python3 herramientas/probar_vivo.py --json

Devuelve 0 si leyó un estado y 1 si no (con el motivo impreso, nunca un estado falseado).
"""
import argparse
import json
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.fuentes import live_api  # noqa: E402


def cuenta_de_los_archivos():
    """Account id desde ABRAMS_CUENTA o `.cuenta`, como hace `arrancar.sh`."""
    valor = os.environ.get("ABRAMS_CUENTA", "").strip()
    if not valor:
        try:
            with open(os.path.join(RAIZ, ".cuenta"), encoding="utf-8") as f:
                valor = f.read().strip()
        except OSError:
            return None
    try:
        return int(valor)
    except ValueError:
        return None


def match_por_cuenta(cuenta):
    """La partida que la API le asigna a esa cuenta, si está jugando ahora."""
    datos = live_api._get_json(
        f"{live_api.BASE}/v1/matches/active?account_id={int(cuenta)}")
    for partida in datos or []:
        if partida.get("match_id"):
            return int(partida["match_id"])
    return None


def match_por_log():
    try:
        from coach.fuentes import log_juego
        if not log_juego.disponible():
            return None
        valor = log_juego.match_id()
        return int(valor) if valor else None
    except Exception:                                          # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", type=int, default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--cuenta", type=int, default=None)
    ap.add_argument("--segundos", type=float, default=6.0)
    ap.add_argument("--json", action="store_true", help="salida legible por máquina")
    a = ap.parse_args()

    cuenta = a.cuenta or cuenta_de_los_archivos()
    origen = None
    match = a.match
    if match is None and a.url is None:
        match = match_por_log()
        origen = "console.log" if match else None
        if match is None and cuenta is not None:
            try:
                match = match_por_cuenta(cuenta)
                origen = "api (cuenta)"
            except Exception as exc:                           # noqa: BLE001
                print(f"AVISO: /matches/active falló: {type(exc).__name__}: {exc}",
                      file=sys.stderr)

    if match is None and a.url is None:
        print("sin partida: ni --match, ni console.log, ni la API por cuenta dan una.")
        print("si estás en partida, revisa que el juego escriba console.log "
              "(`-condebug`) o pasa --match <id>.")
        return 1

    print(f"match: {match if match is not None else '(de la URL)'}"
          f"{f' · origen {origen}' if origen else ''}"
          f"{f' · cuenta {cuenta}' if cuenta else ''}")

    t0 = time.time()
    url = a.url or live_api.url_broadcast(match)
    if not url:
        print(f"sin URL de TV: {live_api.metricas()['ultimo_error']}")
        print("eso es lo que hay que vigilar en la siguiente partida: si aquí sale "
              "k_eNotInGame con la partida en curso, el id no era de una partida viva.")
        return 1
    print(f"url TV: {url} · en {time.time() - t0:.2f} s")

    t1 = time.time()
    estado = live_api.instantanea(url=url, cuenta=cuenta, segundos=a.segundos)
    if estado is None:
        print(f"sin estado: {live_api.metricas()['ultimo_error']}")
        return 1

    if a.json:
        print(json.dumps(estado, ensure_ascii=False))
        return 0

    try:
        from coach import telemetria
        telemetria.anotar("api_prueba", match=match, via="api", rechazo=False,
                          detalle=f"{len(estado['jugadores'])} jugadores en "
                                  f"{time.time() - t1:.2f} s · reloj {estado['t']:.0f} s",
                          latencia_s=round(time.time() - t1, 2))
    except Exception:                                          # noqa: BLE001
        pass

    jugadores = estado["jugadores"]
    print(f"estado en {time.time() - t1:.2f} s · reloj {estado['t']:.0f} s "
          f"(tick {estado['tick']}) · {len(jugadores)} jugadores")
    if estado.get("yo"):
        print(f"yo: {estado['yo']['heroe']} · almas {estado['yo']['almas']} "
              f"· ítems {len(estado['yo'].get('items') or [])}")
    print()
    print(f"{'eq':>2} {'héroe':<14} {'almas':>7} {'oro':>6} {'K/D/A':>9} {'ítems':>6}")
    for j in sorted(jugadores, key=lambda j: -(j.get("almas") or 0)):
        kda = f"{j['bajas']}/{j['muertes']}/{j['asistencias']}"
        print(f"{str(j['equipo']):>2} {str(j['heroe']):<14} {str(j['almas']):>7} "
              f"{str(j['oro']):>6} {kda:>9} {len(j.get('items') or []):>6}")
    print()
    print("métricas:", live_api.metricas())
    print("esto es lo que hoy se saca de píxeles: reloj, almas, oro, ítems y enemigos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
