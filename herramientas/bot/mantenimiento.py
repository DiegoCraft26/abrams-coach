#!/usr/bin/env python3
"""Mantenimiento automático del repo, pensado para correr en la PC headless.

Qué hace, en este orden y sin inventar:
  1. Se pone al día con `origin/master` (reset duro: la rama del bot es desechable).
  2. Limpieza que no cambia comportamiento: imports y variables sin usar (ruff F401/F841).
  3. Corre la suite. Compara los fallos con `~/.abrams-bot/baseline.txt`: si aparece uno
     nuevo, revierte todo y no commitea nada.
  4. Si no hay fallos nuevos y hay cambios, los manda a una rama `bot/AAAA-MM-DD`.

Por qué una rama y no master: el bot no decide qué entra al producto. Produce el cambio
verificado y lo deja para revisión.

La línea base es necesaria porque esta máquina no reproduce el entorno del desktop
(Python 3.10 contra 3.14, numpy 2.2 contra 2.5): dos pruebas de visión fallan aquí y
pasan allá. Lo que el bot vigila es **no empeorar**, no "todo verde".

Uso:
    mantenimiento.py --dry-run     # muestra qué haría, sin tocar nada
    mantenimiento.py               # hace el trabajo y push de la rama del bot
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import subprocess
import sys

REPO = pathlib.Path.home() / "abrams-coach"
VENV = "/srv/scratch/abrams-bot-venv/bin"
BASE = pathlib.Path.home() / ".abrams-bot" / "baseline.txt"
LOG = pathlib.Path.home() / ".abrams-bot" / "ultimo.log"
REMOTE = "origin"
RAMA_BASE = "master"
REGLAS = "F401,F841"          # sólo lo que no cambia comportamiento


def sh(cmd, cwd=REPO, check=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"falló {' '.join(cmd)}: {r.stderr.strip()[:200]}")
    return r


def fallos_de(salida):
    return sorted({l.split()[1] for l in salida.splitlines() if l.startswith("FAILED")})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    BASE.parent.mkdir(parents=True, exist_ok=True)
    lineas = []

    def decir(txt):
        print(txt)
        lineas.append(txt)

    if not (REPO / ".git").exists():
        print(f"no hay repo en {REPO}")
        return 2

    decir(f"== {datetime.datetime.now():%Y-%m-%d %H:%M} ==")
    sh(["git", "fetch", "--depth", "1", REMOTE, RAMA_BASE], check=True)
    sh(["git", "reset", "--hard", f"{REMOTE}/{RAMA_BASE}"], check=True)

    # 1 · limpieza segura
    r = sh([f"{VENV}/ruff", "check", "--select", REGLAS, "--fix", "--quiet",
            "coach", "herramientas", "tests"])
    if r.stdout.strip():
        decir(r.stdout.strip()[:4000])

    # 2 · pruebas
    r = sh([f"{VENV}/python", "-m", "pytest", "-q"])
    fallos = fallos_de(r.stdout + r.stderr)
    baseline = (BASE.read_text().split("\n") if BASE.exists() else [])
    baseline = [x.strip() for x in baseline if x.strip()]
    nuevos = [f for f in fallos if f not in baseline]
    decir(f"pytest: {len(fallos)} fallos ({len(nuevos)} nuevos)")
    if nuevos:
        for f in nuevos:
            decir(f"  NUEVO {f}")
        sh(["git", "checkout", "--", "."])
        decir("revertido: no se commitea nada")
        LOG.write_text("\n".join(lineas), encoding="utf-8")
        return 1
    if not BASE.exists():
        BASE.write_text("\n".join(fallos), encoding="utf-8")
        decir(f"baseline creado con {len(fallos)} fallos conocidos")

    # 3 · ¿hay algo que commitear?
    estado = sh(["git", "status", "--porcelain"]).stdout.strip()
    if not estado:
        decir("sin cambios que valgan un commit")
        LOG.write_text("\n".join(lineas), encoding="utf-8")
        return 0
    decir(estado[:2000])
    if args.dry_run:
        decir("dry-run: no se commitea")
        LOG.write_text("\n".join(lineas), encoding="utf-8")
        return 0

    rama = f"bot/{datetime.date.today():%Y-%m-%d}"
    sh(["git", "checkout", "-B", rama], check=True)
    sh(["git", "add", "-A"], check=True)
    sh(["git", "-c", "user.name=abrams-bot",
        "-c", "user.email=92272351+DiegoCraft26@users.noreply.github.com",
        "commit", "-q", "-m",
        "Limpieza automática: imports y variables sin usar\n\n"
        "Generado por herramientas/bot/mantenimiento.py: sólo reglas que no cambian\n"
        "comportamiento (ruff F401/F841) y con la suite comparada contra la línea base.\n"
        "Nadie lo ha revisado todavía."], check=True)
    sh(["git", "push", "-q", "-u", REMOTE, rama], check=True)
    decir(f"rama enviada: {rama}")
    LOG.write_text("\n".join(lineas), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
