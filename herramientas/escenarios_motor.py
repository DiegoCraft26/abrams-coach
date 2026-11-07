#!/usr/bin/env python3
"""Escenarios sintéticos para medir reglas que el replay no puede medir.

`data/replay_cache.json` trae la línea de tiempo de compras y el net worth **propio**,
pero no las almas de los enemigos. Por eso el modo comeback (comprar barato cuando vas
atrás) no se puede evaluar rejugando: se mide aquí, con el mismo estado y solo cambiando
la economía enemiga.

Cada escenario se corre con las reglas nuevas apagadas y encendidas, y se imprime la
primera recomendación de cada lado. Nada de esto inventa datos: los estados son
explícitos y los ítems salen del conocimiento real del proyecto.

Uso:  python3 herramientas/escenarios_motor.py
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.motor_api import Motor  # noqa: E402

APAGADO = {"w_presupuesto": 0.0, "w_recuperacion": 0.0, "w_balance": 0.0,
           "contexto_activo": False}

ITEMS_BASE = ["1342610602", "1437614329", "4139877411"]
COMP_NEUTRA = ["bebop", "viscous", "apollo", "billy", "calico"]
COMP_CURA = ["dynamo", "kelvin", "ivy", "wraith", "paige"]
COMP_SPIRIT = ["haze", "seven", "pocket", "geist", "infernus"]
COMP_CC = ["mirage", "mcginnis", "bebop", "warden", "vindicta"]
COMP_MOVIL = ["haze", "pocket", "wraith", "lash", "infernus"]


def estado(t, almas, almas_enemigas, heroes, items=None):
    return {
        "t": t,
        "yo": {"heroe": "Abrams", "almas": almas, "items": items or list(ITEMS_BASE)},
        "aliados": [{"heroe": "kelvin", "almas": almas}],
        "enemigos": [{"heroe": h, "almas": almas_enemigas} for h in heroes],
        "confianza": 1.0, "fuente": "escenario",
    }


ESCENARIOS = [
    ("adelante 25% · min 18", estado(1080, 12000, 9000, COMP_NEUTRA)),
    ("atrás 25% · min 18", estado(1080, 9000, 12000, COMP_NEUTRA)),
    ("atrás 35% · min 25", estado(1500, 10000, 15400, COMP_NEUTRA)),
    ("parejo · min 18", estado(1080, 12000, 12000, COMP_NEUTRA)),
    ("composición con curación", estado(1500, 14000, 14000, COMP_CURA)),
    ("composición spirit", estado(1500, 14000, 14000, COMP_SPIRIT)),
    ("composición con control", estado(1500, 14000, 14000, COMP_CC)),
    ("composición con movilidad", estado(1500, 14000, 14000, COMP_MOVIL)),
]


def primera(motor, est, n=3):
    r = motor.analizar_dict(est)
    recos = (r.get("recomendaciones") or [])[:n]
    if not recos:
        return None
    return {"nombres": [x["nombre"] for x in recos],
            "costos": [x.get("costo") for x in recos],
            "nombre": recos[0]["nombre"], "costo": recos[0].get("costo"),
            "residual": recos[0].get("residual"),
            "razones": recos[0].get("razones") or []}


def main():
    apagado = Motor(cfg=dict(APAGADO))
    encendido = Motor()
    solo_recuperacion = Motor(cfg={**APAGADO, "w_recuperacion": 0.9})
    filas = []

    print("== top-3 por escenario (reglas nuevas apagadas -> encendidas) ==")
    for nombre, est in ESCENARIOS:
        a = primera(apagado, est)
        b = primera(encendido, est)
        cambia = "≠" if (a and b and a["nombre"] != b["nombre"]) else "="
        print(f"{nombre:30} ANTES {', '.join(a['nombres'])[:52]:52} "
              f"DESPUÉS {', '.join(b['nombres'])[:52]:52} {cambia}")
        filas.append({"escenario": nombre, "antes": a, "despues": b,
                      "cambia": cambia})

    print()
    print("== solo la regla de comeback (yendo atrás vs yendo adelante) ==")
    for nombre, est in ESCENARIOS[:3]:
        base = primera(apagado, est, 1)
        solo = primera(solo_recuperacion, est, 1)
        print(f"{nombre:30} sin regla {base['nombre'][:22]:22} {base['costo']:>5} · "
              f"con regla {solo['nombre'][:22]:22} {solo['costo']:>5}")

    print()
    cambios = sum(1 for f in filas if f["cambia"] == "≠")
    print(f"escenarios con recomendación distinta: {cambios}/{len(filas)}")
    ruta = os.path.join(RAIZ, "informes", "escenarios-motor.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)
    print("guardado:", ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
