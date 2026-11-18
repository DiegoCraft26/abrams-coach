#!/usr/bin/env python3
"""¿La app abierta es la más reciente? Responde sin abrir nada.

    herramientas/version.py          # texto legible, sale 0 si está al día y 2 si no
    herramientas/version.py --json   # el dict de /api/version
    herramientas/version.py --subir  # git pull --ff-only y avisa si hace falta reiniciar

Compara el código en disco (commit + huella de los .py) con el que marcó la app al
arrancar, y con el remoto. Ver docs/VERSION.md.
"""
import argparse
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from coach import version  # noqa: E402

AL_DIA = {"si", "probable_si"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="salida JSON cruda")
    ap.add_argument("--subir", action="store_true",
                    help="git pull --ff-only antes de comparar")
    a = ap.parse_args()

    if a.subir:
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=RAIZ,
                           capture_output=True, text=True)
        print((r.stdout or r.stderr).strip() or "(sin salida)")

    datos = version.comparar()
    if a.json:
        print(json.dumps(datos, ensure_ascii=False, indent=2))
    else:
        print(version.resumen(datos))
    return 0 if datos["veredicto"] in AL_DIA else 2


if __name__ == "__main__":
    sys.exit(main())
