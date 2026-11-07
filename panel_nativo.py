#!/usr/bin/env python3
"""Panel nativo GTK4 del Abrams Coach.

Este archivo es solo el punto de entrada: la ventana, los componentes y el tema viven en
`coach/ui/`. Se mantiene el nombre y los argumentos para no romper `arrancar.sh`,
`modo_juego.sh` ni los hábitos de la sesión anterior.

Uso:
    python3 panel_nativo.py                     # panel contra http://127.0.0.1:8090
    python3 panel_nativo.py --breakpoint medio   # forzar un reparto (para capturas)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--pantalla", type=int, default=None,
                    help="(compatibilidad) monitor sugerido; lo decide el gestor de ventanas")
    ap.add_argument("--breakpoint", default="auto",
                    choices=["auto", "angosto", "medio", "amplio"],
                    help="fuerza el reparto de columnas; auto = según el ancho")
    ap.add_argument("--intervalo", type=float, default=1.0,
                    help="segundos entre consultas a /api/estado")
    ap.add_argument("--ancho", type=int, default=None, help="ancho inicial en px")
    ap.add_argument("--alto", type=int, default=None, help="alto inicial en px")
    a = ap.parse_args()

    from coach.ui import App
    tamano = (a.ancho, a.alto) if a.ancho and a.alto else None
    App(a.url, a.breakpoint, a.intervalo, tamano).run(None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
