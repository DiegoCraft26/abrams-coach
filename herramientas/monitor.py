#!/usr/bin/env python3
"""Monitor del coach durante una partida.

Muestrea /api/estado cada N segundos, guarda una línea JSON por muestra y avisa
de anomalías: stream congelado, almas que bajan, recomendaciones vacías o
incoherentes con el oro, panel muerto.

Uso:
    python3 monitor.py --match 132869067 [--intervalo 5] [--max 3600]
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:8090/api/estado"
PID_PANEL = "/tmp/abrams-panel.pid"
PID_COACH = "/tmp/abrams-coach.pid"


def vivo(pidfile):
    try:
        pid = int(open(pidfile).read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def leer():
    with urllib.request.urlopen(URL, timeout=5) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", type=int, required=True)
    ap.add_argument("--intervalo", type=float, default=5.0)
    ap.add_argument("--max", type=int, default=3600)
    a = ap.parse_args()

    os.makedirs(os.path.join(BASE, "salida"), exist_ok=True)
    ruta = os.path.join(BASE, "salida", f"monitor-{a.match}.jsonl")
    arranque = time.time()
    t_previo = None
    iguales = 0
    sin_listo = 0
    almas_previas = None
    muestras = 0

    with open(ruta, "a") as f:
        while time.time() - arranque < a.max:
            try:
                d = leer()
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] sin API: {exc}", flush=True)
                time.sleep(a.intervalo)
                continue

            muestras += 1
            t = d.get("t")
            eco = d.get("economia") or {}
            recs = d.get("recomendaciones") or []
            fila = {
                "ts": round(time.time(), 1),
                "t": t,
                "estado": (d.get("estado") or {}).get("estado"),
                "almas": eco.get("mias"),
                "oro": d.get("oro"),
                "delta": round((eco.get("delta_pct") or 0) * 100, 1),
                "recs": [[r.get("nombre"), r.get("costo"), r.get("alcanza"), r.get("faltan")]
                         for r in recs[:3]],
                "listo": d.get("listo"),
                "rancio": d.get("rancio"),
                "msg": d.get("mensaje"),
            }
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
            f.flush()

            # 1. stream congelado
            if t is not None and t == t_previo:
                iguales += 1
            else:
                iguales = 0
                t_previo = t
            if iguales >= 4:
                print(f"[{time.strftime('%H:%M:%S')}] CONGELADO t={t} "
                      f"({iguales * a.intervalo:.0f}s sin avanzar)", flush=True)

            # 2. sin conexión
            if d.get("listo") is False and "no está en partida" not in str(d.get("mensaje")):
                sin_listo += 1
                if sin_listo == 3:
                    print(f"[{time.strftime('%H:%M:%S')}] SIN DATOS: {d.get('mensaje')}",
                          flush=True)
            else:
                sin_listo = 0

            # 3. almas que bajan (el patrimonio no debe caer)
            almas = eco.get("mias")
            if almas is not None and almas_previas is not None and almas < almas_previas - 1500:
                print(f"[{time.strftime('%H:%M:%S')}] ALMAS BAJAN {almas_previas} -> {almas}",
                      flush=True)
            almas_previas = almas

            # 4. recomendación incoherente con el oro
            oro = d.get("oro")
            if oro is not None and recs:
                r = recs[0]
                costo = r.get("costo") or 0
                if r.get("alcanza") is False and costo <= oro:
                    print(f"[{time.strftime('%H:%M:%S')}] INCOHERENTE: {r.get('nombre')} "
                          f"cuesta {costo} y hay {oro}", flush=True)
                if r.get("alcanza") is True and costo > oro:
                    print(f"[{time.strftime('%H:%M:%S')}] INCOHERENTE: {r.get('nombre')} "
                          f"cuesta {costo} y solo hay {oro}", flush=True)

            # 5. procesos vivos
            if not vivo(PID_PANEL):
                print(f"[{time.strftime('%H:%M:%S')}] PANEL CAÍDO", flush=True)
            if not vivo(PID_COACH):
                print(f"[{time.strftime('%H:%M:%S')}] COACH CAÍDO", flush=True)

            # 6. fin de partida: sin datos 60 s
            if sin_listo >= 12:
                print(f"[{time.strftime('%H:%M:%S')}] FIN: 60 s sin broadcast", flush=True)
                break

            time.sleep(a.intervalo)

    print(f"monitor: {muestras} muestras en {ruta}", flush=True)


if __name__ == "__main__":
    main()
