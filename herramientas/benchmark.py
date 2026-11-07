#!/usr/bin/env python3
"""Alias de `evaluar_motor.py` (el nombre que pedía la arquitectura objetivo).

Mide el motor sobre partidas reales y compara configuraciones. Ver
`herramientas/evaluar_motor.py` para el detalle de las métricas.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "herramientas"))

from evaluar_motor import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
