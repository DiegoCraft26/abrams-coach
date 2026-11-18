"""Datos locales que no viajan en el repo público.

`datos/lab.db` (359 MB de corpus) y `data/items.json` (catálogo descargable) están fuera
del repo por tamaño y por política: cada quien los regenera con las herramientas del
repo. Cuando faltan, la prueba no puede afirmar nada, así que se omite a la vista en vez
de reventar con un FileNotFoundError que parece un bug del código.
"""
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def falta(*rutas):
    """Las rutas indicadas que no existen, relativas a la raíz del proyecto."""
    return [r for r in rutas if not os.path.exists(os.path.join(RAIZ, r))]
