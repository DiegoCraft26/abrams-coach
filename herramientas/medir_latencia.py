#!/usr/bin/env python3
"""Mide la cadena de latencia del coach, eslabón por eslabón.

Sin juego abierto mide lo que sí se puede medir (captura y OCR) y dice qué falta. Con el
juego abierto, además compara el reloj del HUD contra el del broadcast para dar la
latencia real del TV de Valve.

Uso:
    python3 herramientas/medir_latencia.py                 # 10 ciclos
    python3 herramientas/medir_latencia.py --ciclos 30
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

from coach.fuentes import captura, hud_rapido  # noqa: E402


def _estado_panel(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/estado", timeout=2) as r:
            return json.load(r)
    except Exception:                                    # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ciclos", type=int, default=10)
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    a = ap.parse_args()

    print("eslabones medidos separado (ms):")
    cap = captura.CapturaCompartida().arrancar()
    time.sleep(1.5)

    filas = []
    for _ in range(a.ciclos):
        t0 = time.perf_counter()
        datos = hud_rapido.leer_actual()
        total = (time.perf_counter() - t0) * 1000
        if datos:
            filas.append({"total": total, **datos})
        time.sleep(0.15)

    m = cap.metricas()
    print(f"  captura   {m['ms_mediana']} ms (p95 {m['ms_p95']}, "
          f"{m['capturas']} cuadros, {m['fallos']} fallos)")
    if filas:
        print(f"  reloj     {statistics.median([f['ms_reloj'] for f in filas]):.0f} ms")
        print(f"  oro       {statistics.median([f['ms_oro'] for f in filas]):.0f} ms")
        print(f"  ciclo HUD {statistics.median([f['total'] for f in filas]):.0f} ms "
              f"-> {1000/statistics.median([f['total'] for f in filas]):.1f} Hz")
        relojes = [f["t"] for f in filas if f.get("t") is not None]
        oros = [f["oro"] for f in filas if f.get("oro") is not None]
        print(f"  lecturas  reloj {len(relojes)}/{len(filas)} · oro {len(oros)}/{len(filas)}"
              .replace("  ", " "))
        if relojes:
            print(f"  reloj leído {min(relojes)}–{max(relojes)} s")
        if oros:
            print(f"  oro leído   {min(oros):,}–{max(oros):,}")
        if not relojes and not oros:
            print("  (sin juego abierto no hay HUD que leer: esto es lo esperado)")
    else:
        print("  HUD       sin cuadros utilizables")

    est = _estado_panel(a.url)
    if est:
        lat = est.get("latencia") or {}
        print("lo que publica el panel ahora:")
        print(f"  edad del estado ....... {est.get('edad_s')} s")
        for clave in ("captura_ms", "lectura_ms", "broadcast_s"):
            if clave in lat:
                print(f"  {clave:.<22} {lat[clave]}")
    else:
        print(f"panel: sin respuesta en {a.url} (no se puede medir la latencia del broadcast)")

    cap.parar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
