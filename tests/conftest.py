"""Pytest: raíz del proyecto en sys.path y suites con nombre propio.

Las suites están escritas para correr como scripts (`python3 tests/test_x.py`).
Cada módulo expone además `test_suite()` para que `pytest -q` las ejecute igual.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
