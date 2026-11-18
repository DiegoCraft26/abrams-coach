#!/bin/bash
# Corre una herramienta del coach en la PC (<pc-auxiliar>), no en la de jugar.
#
# Para qué: el banco de 626 partidas, tesoros, el meta por parche y los informes no
# necesitan la pantalla y comen CPU durante minutos. Ahí la PC de 4 hilos tarda ~2x más,
# pero el escritorio queda libre (y sin tirón en la partida).
#
#   herramientas/en_pc.sh banco_partidas.py --partidas 626 --cada 30
#   herramientas/en_pc.sh --traer banco_partidas.py --partidas 120
#   herramientas/en_pc.sh --sin-sync meta_abrams.py
#
# El árbol se sincroniza antes de cada llamada (0.8 s por gigabit, incluye data/ con las
# 626 partidas). `--sin-sync` se salta ese paso cuando solo cambian argumentos.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO=/srv/abrams/coach
PY=/srv/abrams/venv/bin/python
TRAER=0
SYNC=1

while [ $# -gt 0 ]; do
  case "$1" in
    --traer) TRAER=1; shift ;;
    --sin-sync) SYNC=0; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    --) shift; break ;;
    -*) echo "opción desconocida: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done

[ $# -ge 1 ] || { echo "falta el script (p. ej. banco_partidas.py)" >&2; exit 2; }

if [ "$SYNC" = 1 ]; then
  rsync -az --delete \
    --exclude=grabaciones --exclude=capturas --exclude=.git --exclude=salida \
    --exclude=datos --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=verdad --exclude=experimentos \
    "$RAIZ"/ "pc:$DESTINO"/
fi

CMD="$1"; shift
echo "→ pc: $CMD $*" >&2
ssh pc "cd $DESTINO && $PY herramientas/$CMD $*"

if [ "$TRAER" = 1 ]; then
  rsync -az "pc:$DESTINO/salida/" "$RAIZ/salida/" 2>/dev/null || true
  echo "← salida/ traída de la PC" >&2
fi
