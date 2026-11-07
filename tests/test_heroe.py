"""Datos por héroe: se leen de archivo, hay respaldo y el motor los usa.

El objetivo del cambio del 2026-11-07 era sacar Abrams del código para poder añadir héroes
sin tocar el motor. Esto comprueba que el respaldo funciona y que un archivo roto no rompe
la app.
"""
import json
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.decision import heroe  # noqa: E402
from coach.motor_api import Motor  # noqa: E402


def main():
    fallos = 0

    def check(nombre, cond, detalle=""):
        nonlocal fallos
        if cond:
            print(f"  ok   {nombre}")
        else:
            print(f"  FALLA {nombre} {detalle}")
            fallos += 1

    print("héroe por defecto")
    h = heroe.cargar("abrams")
    check("carga Abrams", h.nombre == "Abrams", h.datos.get("nombre"))
    check("trae hitos", len(h.hitos) >= 2, str(h.hitos))
    check("trae fases", len(h.fases) == 3, str(h.fases))
    check("trae apertura", len(h.apertura) >= 3, str(len(h.apertura)))

    print("respaldo")
    raro = heroe.cargar("haze")
    check("héroe sin datos cae a Abrams", raro.nombre == "Abrams", raro.nombre)
    check("no lanza con None", heroe.cargar(None).nombre == "Abrams")

    print("datos del motor")
    m = Motor()
    estado = {"t": 1500, "yo": {"heroe": "Abrams", "almas": 14000, "items": []},
              "enemigos": [{"heroe": "haze", "almas": 14000}], "confianza": 1.0}
    r = m.analizar_dict(estado)
    check("el motor reporta el héroe", r.get("heroe_datos") == "abrams", str(r.get("heroe_datos")))
    check("trae fase económica", r.get("fase_economica") in ("EARLY", "MID", "LATE", "CIERRE"),
          str(r.get("fase_economica")))
    check("recomienda algo", bool(r.get("recomendaciones")), "sin recomendaciones")

    # un héroe sin archivo propio debe decidir igual, con los datos de Abrams
    estado2 = dict(estado)
    estado2["yo"] = {"heroe": "Haze", "almas": 14000, "items": []}
    r2 = m.analizar_dict(estado2)
    check("héroe desconocido no rompe", bool(r2.get("recomendaciones")))
    check("y usa los datos de Abrams", r2.get("heroe_datos") == "abrams",
          str(r2.get("heroe_datos")))

    print("archivo roto")
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "roto.json")
        with open(ruta, "w") as f:
            f.write("{no es json")
        original = heroe.DIR
        heroe.DIR = tmp
        heroe._cache.clear()
        try:
            roto = heroe.cargar("roto")
            check("JSON roto -> respaldo", roto.nombre == "Abrams", roto.nombre)
        finally:
            heroe.DIR = original
            heroe._cache.clear()

    print()
    if fallos:
        print(f"heroe: {fallos} fallos")
        return 1
    print("heroe: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
