#!/usr/bin/env python3
"""Humo del camino en vivo: arranca el coach, inyecta un estado y comprueba la cadena.

No abre el juego ni captura pantalla: usa `--fuente simulado` y el gancho
`POST /api/simular` que ya existe para depurar. Lo que verifica es lo que el jugador ve:

  1. `/api/estado` responde y trae camino, recomendaciones y `decision`.
  2. Con KDA inyectado (7 muertes, 0.73 de participación), el perfil de riesgo sale y
     marca el corte de muertes.
  3. `/panel` y `/tarjeta` se sirven y **no** prometen oro («te alcanza», «faltan ~»).

Uso:
    python3 herramientas/humo_vivo.py
    python3 herramientas/humo_vivo.py --verboso

Sale 0 si todo pasa; 1 si algo falla. Pensado para CI y para después de tocar el motor.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable or "python3"


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def esperar(url: str, limite: float = 40.0):
    fin = time.time() + limite
    while time.time() < fin:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:      # noqa: S310
                return json.loads(r.read())
        except Exception:                                          # noqa: BLE001
            time.sleep(0.4)
    return None


def post_json(url: str, datos: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(datos).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:          # noqa: S310
            return r.status, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Humo del camino en vivo")
    ap.add_argument("--verboso", action="store_true")
    a = ap.parse_args(argv)
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    log = open("/tmp/abrams-humo.log", "w", encoding="utf-8")
    proc = subprocess.Popen([PY, "run.py", "--fuente", "simulado", "--puerto", str(puerto)],
                            cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT)
    fallos = []

    def check(nombre, cond, detalle=""):
        print(("  ok   " if cond else "  FALLA ") + nombre + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    try:
        d = esperar(f"{base}/api/estado")
        if d is None:
            check("el coach arranca y publica estado", False)
            return 1
        check("el coach arranca y publica estado", True)
        check("trae camino", bool(d.get("camino")), str(len(d.get("camino") or [])))
        check("trae recomendaciones", bool(d.get("recomendaciones")))
        check("trae decisión", bool(d.get("decision")))

        estado_vivo = {"t": 900, "fuente": "manual",
                       "yo": {"heroe": "abrams", "almas": 9000, "items": [],
                              "bajas": 3, "muertes": 7, "asistencias": 8},
                       "aliados": [], "enemigos": []}
        codigo, cuerpo = post_json(f"{base}/api/simular", estado_vivo)
        check("el gancho de simulación acepta el estado", codigo == 200, f"{codigo} {cuerpo}")
        d2 = esperar(f"{base}/api/estado", limite=10)
        riesgo = (d2 or {}).get("riesgo") or {}
        check("sale el perfil de riesgo con KDA", bool(riesgo), json.dumps(riesgo)[:120])
        check("marca el corte de muertes", riesgo.get("cruza_muertes") is True,
              str(riesgo.get("muertes")))
        check("calcula la participación", abs((riesgo.get("participacion") or 0) - 0.73) < 0.02,
              str(riesgo.get("participacion")))

        for ruta in ("/panel", "/tarjeta"):
            try:
                with urllib.request.urlopen(base + ruta, timeout=5) as r:   # noqa: S310
                    html = r.read().decode("utf-8", "ignore")
                check(f"{ruta} responde", bool(html))
                if ruta == "/panel":
                    check("el panel no promete oro",
                          "ya te alcanza" not in html and "faltan ~" not in html)
            except Exception as exc:                                        # noqa: BLE001
                check(f"{ruta} responde", False, str(exc))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    if a.verboso or fallos:
        try:
            with open("/tmp/abrams-humo.log", encoding="utf-8") as f:
                cola = f.read().strip().splitlines()[-12:]
            if cola:
                print("--- log del coach ---")
                print("\n".join(cola))
        except OSError:
            pass
    print(("todo ok" if not fallos else f"FALLOS: {fallos}"))
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
