#!/usr/bin/env python3
"""Modo espera: arranca el coach cuando abres Deadlock y lo cierra cuando sales.

Es lo que hace que la app se sienta parte del juego sin tocar el juego: solo mira la lista
de procesos cada pocos segundos.

Uso:
    python3 herramientas/vigilar.py            # espera, arranca, cierra y archiva
    python3 herramientas/vigilar.py --sin-panel

Al terminar la partida: cierra el coach, archiva en SQLite y escribe el informe.
"""
import argparse
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

LOG = "/tmp/abrams-vigilar.log"


def registrar(texto):
    linea = f"{time.strftime('%H:%M:%S')} {texto}"
    print(linea, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def juego_abierto():
    """True si Deadlock corre. Se mira la lista de argumentos porque `comm` es wine."""
    try:
        salida = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                                text=True, timeout=5).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return any(n in salida for n in ("deadlock.exe", "deadlock/game/bin", "project8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-panel", action="store_true")
    ap.add_argument("--intervalo", type=float, default=5.0)
    a = ap.parse_args()

    registrar("modo espera: abre Deadlock cuando quieras")
    procesos = []
    dentro = False
    while True:
        abierto = juego_abierto()
        if abierto and not dentro:
            dentro = True
            registrar("Deadlock abierto: arrancando el coach")
            try:
                procesos.append(subprocess.Popen(
                    [sys.executable, os.path.join(RAIZ, "run.py"), "--fuente", "auto"],
                    cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                if not a.sin_panel:
                    time.sleep(2)
                    procesos.append(subprocess.Popen(
                        [sys.executable, os.path.join(RAIZ, "panel_nativo.py")],
                        cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            except OSError as exc:
                registrar(f"no pude arrancar: {exc}")
        elif not abierto and dentro:
            dentro = False
            registrar("Deadlock cerrado: cerrando y archivando")
            for p in procesos:
                try:
                    p.terminate()
                except OSError:
                    pass
            procesos = []
            time.sleep(3)
            try:
                salida = subprocess.run(
                    [sys.executable, os.path.join(RAIZ, "herramientas", "archivar.py")],
                    cwd=RAIZ, capture_output=True, text=True, timeout=120)
                for linea in (salida.stdout or "").strip().splitlines()[-4:]:
                    registrar("  " + linea)
            except (OSError, subprocess.SubprocessError) as exc:
                registrar(f"  el archivado falló: {exc}")
        time.sleep(max(2.0, a.intervalo))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nmodo espera terminado")
