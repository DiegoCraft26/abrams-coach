#!/usr/bin/env python3
"""¿El plan oscila de verdad o lo parece? Estabilidad cruda contra histéresis.

`evaluar_motor.py` mide estabilidad como «dos estados seguidos con el mismo top-1». Eso
es duro con un motor sin memoria: cualquier cambio de fase puede mover la tarjeta. En
vivo, `coach/estabilizador.py` mantiene la recomendación hasta que la nueva se repite o
pasa un tiempo, así que lo que ve el jugador no es la secuencia cruda.

Este script mide las dos cosas sobre el mismo corpus y con el mismo motor:

    cruda       cambio de top-1 entre minutos consecutivos
    histéresis  el plan sólo cambia cuando la nueva recomendación se repite N veces
                seguidas o cuando pasa `--ventana` segundos

Uso:
    python3 herramientas/lab/estabilidad.py --cache data/replay_actual.json
    python3 herramientas/lab/estabilidad.py --repeticiones 2 --ventana 60
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from coach.motor_api import Motor  # noqa: E402


def _evaluador():
    ruta = os.path.join(RAIZ, "herramientas", "evaluar_motor.py")
    spec = importlib.util.spec_from_file_location("evaluar_motor", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser(description="Estabilidad cruda vs histéresis")
    ap.add_argument("--cache", default=os.path.join(RAIZ, "data", "replay_actual.json"))
    ap.add_argument("--partidas", type=int, default=150)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--ventana", type=int, default=60, help="segundos máximos de espera")
    ap.add_argument("--desde-min", type=int, default=6)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    ev = _evaluador()
    motor = Motor(json.loads(args.config) if args.config else None)
    heroes = {k: v["nombre"].lower().replace(" ", "_")
              for k, v in json.load(open(os.path.join(RAIZ, "data", "heroes.json"))).items()}
    partidas = ev.cargar_cache(args.partidas, args.cache)

    crudo = [0, 0]          # [estables, total]
    hist = [0, 0]
    for partida in partidas:
        seq = []
        fin = partida.get("duracion_s") or 0
        t = args.desde_min * 60
        while t <= fin:
            estado = ev.estado_en(partida, t, heroes)
            if estado["yo"]["almas"] and estado["enemigos"]:
                r = motor.analizar_dict(estado)
                recos = r.get("recomendaciones") or []
                seq.append((t, recos[0]["id"] if recos else None))
            t += 60
        ids = [x[1] for x in seq]
        for a, b in zip(ids, ids[1:]):
            crudo[1] += 1
            crudo[0] += (a == b)

        # Histéresis: se mantiene el plan hasta que el nuevo se repita N veces o pase
        # la ventana; igual que `estabilizador.py` en vivo.
        fijado, desde, consecutivo, previo = None, 0, 0, None
        estabilizada = []
        for t, iid in seq:
            if iid == fijado:
                consecutivo = 0
            else:
                consecutivo = consecutivo + 1 if iid == previo else 1
            if (fijado is None or consecutivo >= args.repeticiones
                    or t - desde >= args.ventana):
                if iid != fijado:
                    fijado, desde = iid, t
                    consecutivo = 0
            estabilizada.append(fijado)
            previo = iid
        for a, b in zip(estabilizada, estabilizada[1:]):
            hist[1] += 1
            hist[0] += (a == b)

    print(f"partidas {len(partidas)} · transiciones {crudo[1]:,}")
    print(f"estabilidad cruda ...... {crudo[0]/max(1,crudo[1]):.1%}")
    print(f"estabilidad con histéresis ({args.repeticiones} repeticiones / {args.ventana} s)"
          f" ... {hist[0]/max(1,hist[1]):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
