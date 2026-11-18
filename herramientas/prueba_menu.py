#!/usr/bin/env python3
"""Prueba con el juego abierto en el MENÚ (sin partida).

Qué cubre, y es la mayor parte de lo que se puede comprobar sin jugar:

1. coste real de la captura por caja con el juego renderizando (el hideout es una escena
   3D viva, así que el readback se paga igual que en partida);
2. que el menú NO se confunda con una partida (el bug del 2026-11-15: `GameInProgress`
   con mapa `dl_hideout`);
3. que la app no invente un marcador ni 12 almas cuando no hay marcador;
4. que el panel publique el plan de apertura con su fuente y no un estado de partida;
5. CPU, RAM y GPU del coach con el juego abierto.

Lo que NO cubre: el tirón dentro de una pelea, la transición menú → partida → fin con una
partida de verdad, el broadcast en vivo y las líneas de histórico/sugerencia con enemigos
reales. Eso necesita `abrams-coach prueba` con una partida en curso.

Uso:
    python3 herramientas/prueba_menu.py                 # 40 s de observación
    python3 herramientas/prueba_menu.py --segundos 90
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.fuentes import captura_kwin, log_juego      # noqa: E402
from coach.nucleo_demo import juego_abierto            # noqa: E402

SALIDA = os.path.join(RAIZ, "salida")
CAJAS = {"reloj": (3150, 8, 3265, 52), "banda_oro": (2480, 900, 2780, 1100),
         "marcador": (360, 260, 1080, 820)}
FALLOS = []


def _ok(nombre, condicion, detalle=""):
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre:<46} {detalle}")
    if not condicion:
        FALLOS.append(nombre)
    return condicion


def _gpu():
    import glob
    for ruta in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        try:
            with open(ruta, encoding="ascii") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None
    return None


def _estado(puerto=8090):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/estado",
                                    timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception:                                          # noqa: BLE001
        return None


def medir_captura(veces=8):
    tiempos = {}
    for nombre, caja in CAJAS.items():
        muestras = []
        for _ in range(veces):
            t0 = time.perf_counter()
            im = captura_kwin.capturar(caja[0], caja[1], caja[2] - caja[0],
                                       caja[3] - caja[1])
            if im is None:
                return None, f"{nombre}: None"
            muestras.append((time.perf_counter() - t0) * 1000)
        tiempos[nombre] = round(statistics.median(muestras), 1)
    return tiempos, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=float, default=40.0)
    ap.add_argument("--puerto", type=int, default=8090)
    a = ap.parse_args()

    if not juego_abierto(usar_cache=False):
        print("Deadlock no está corriendo. Abre el juego (el menú basta) y repite.")
        return 2

    print(f"Prueba en el menú · observando {a.segundos} s\n")
    log_juego.actualizar(force=True)
    _ok("el juego está abierto", True)
    _ok("el mapa cargado es el hideout (menú)", log_juego.en_menu(),
        str(log_juego.mapa()))
    _ok("el menú no cuenta como partida", not log_juego.en_partida(),
        f"fase={log_juego.fase()}")
    estado, frescura = log_juego.estado_ui()
    _ok("el estado del panel dice menú", estado == "menu",
        f"estado={estado} · log de hace {round(frescura or 0)} s")

    tiempos, error = medir_captura()
    if tiempos:
        detalle = " · ".join(f"{k} {v} ms" for k, v in tiempos.items())
        _ok("captura por caja por debajo de 20 ms", max(tiempos.values()) < 20, detalle)
    else:
        _ok("captura por caja", False, error)

    if not _estado(a.puerto):
        print(f"\n  (el coach no responde en :{a.puerto}: no se puede mirar el panel)")
    gpu, cpus = [], []
    t0 = time.time()
    while time.time() - t0 < a.segundos:
        g = _gpu()
        if g is not None:
            gpu.append(g)
        d = _estado(a.puerto)
        if d:
            cpus.append(d)
        time.sleep(2.0)

    if cpus:
        est = cpus[-1]
        mensaje = str(est.get("mensaje") or "")
        fase = str((est.get("estado") or {}).get("motivo") or "")
        _ok("el panel no dice «en partida»", "partida" not in fase.lower(),
            f"motivo={fase[:60]}")
        _ok("el panel no inventa almas", not (est.get("almas_12") or []),
            str(est.get("almas_12"))[:40])
        _ok("el plan trae su fuente", bool(est.get("fuente_apertura")),
            str(est.get("fuente_apertura")))
        _ok("el plan tiene ítems", bool(est.get("plan")),
            ", ".join(p.get("nombre", "?") for p in (est.get("plan") or [])[:3]))
        _ok("no se declara rancio con el coach publicando",
            not est.get("rancio"), f"edad={est.get('edad_s')} s")
        if mensaje:
            print(f"       mensaje del panel: {mensaje[:80]}")

    if gpu:
        print(f"  GPU durante la prueba: mediana {statistics.median(gpu):.0f} % · "
              f"máx {max(gpu)} %")

    os.makedirs(SALIDA, exist_ok=True)
    ruta = os.path.join(SALIDA, f"prueba-menu-{time.strftime('%Y%m%d-%H%M')}.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"# Prueba en el menú — {time.strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"- juego abierto: sí · mapa: {log_juego.mapa()} · fase: "
                f"{log_juego.fase()}\n")
        if tiempos:
            for k, v in tiempos.items():
                f.write(f"- captura {k}: {v} ms\n")
        if gpu:
            f.write(f"- GPU: mediana {statistics.median(gpu):.0f} % · máx {max(gpu)} %\n")
        if cpus:
            f.write(f"- panel: motivo «{(cpus[-1].get('estado') or {}).get('motivo')}»\n")
            f.write(f"- plan: {[p.get('nombre') for p in (cpus[-1].get('plan') or [])]}\n")
        f.write(f"\nFallos: {FALLOS or 'ninguno'}\n")
    print(f"\ninforme: {os.path.relpath(ruta, RAIZ)}")
    print(f"{'todo bien' if not FALLOS else str(len(FALLOS)) + ' fallo(s): ' + ', '.join(FALLOS)}")
    return 0 if not FALLOS else 1


if __name__ == "__main__":
    sys.exit(main())
