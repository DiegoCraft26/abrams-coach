#!/usr/bin/env bash
# Instala el "equipo" (contrato, estado, puertas y prompt master) en otro proyecto.
#
# El sistema de agentes no sirve si vive en un solo repo. Este script crea `docs/` en el
# proyecto destino con las cuatro piezas, ya con el nombre y la fecha puestos, y **no
# sobrescribe** nada que exista: si ya hay un ESTADO-ACTUAL, lo dice y sigue.
#
# Uso:
#   herramientas/nuevo-equipo.sh /ruta/al/proyecto "Nombre del proyecto"
#   herramientas/nuevo-equipo.sh /ruta/al/proyecto "Nombre" --forzar
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLANTILLAS="$RAIZ/plantillas/equipo"
FORZAR=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--forzar" ]; then FORZAR=1; else ARGS+=("$a"); fi
done

DESTINO="${ARGS[0]:-}"
NOMBRE="${ARGS[1]:-}"
if [ -z "$DESTINO" ] || [ -z "$NOMBRE" ]; then
  echo "uso: $0 <ruta-del-proyecto> \"<nombre>\" [--forzar]" >&2
  exit 2
fi
if [ ! -d "$DESTINO" ]; then
  echo "no existe el directorio: $DESTINO" >&2
  exit 2
fi
if [ ! -d "$PLANTILLAS" ]; then
  echo "faltan las plantillas en $PLANTILLAS" >&2
  exit 2
fi

DESTINO="$(cd "$DESTINO" && pwd)"
mkdir -p "$DESTINO/docs"
FECHA="$(date +%Y-%m-%d)"

for f in EQUIPO.md ESTADO-ACTUAL.md PUERTAS.md PROMPT-MASTER.md; do
  origen="$PLANTILLAS/$f"
  [ -f "$origen" ] || continue
  destino="$DESTINO/docs/$f"
  if [ -e "$destino" ] && [ "$FORZAR" = "0" ]; then
    echo "  ya existe  docs/$f (no se toca)"
    continue
  fi
  python3 - "$origen" "$destino" "$NOMBRE" "$FECHA" <<'PY'
import sys
origen, destino, nombre, fecha = sys.argv[1:5]
texto = open(origen, encoding="utf-8").read()
texto = texto.replace("<PROYECTO>", nombre).replace("<FECHA>", fecha)
open(destino, "w", encoding="utf-8").write(texto)
PY
  echo "  escrito   docs/$f"
done

echo
echo "Equipo instalado en $DESTINO/docs"
echo "Siguiente: rellena ESTADO-ACTUAL.md antes de lanzar cualquier agente."
