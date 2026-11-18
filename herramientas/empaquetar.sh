#!/usr/bin/env bash
# Construye el tarball que se puede compartir, y lo prueba.
#
# Por qué existe: `git clone` no es una forma de distribuir una app. Esto arma
# `dist/abrams-coach-<versión>.tar.gz` con lo que la app necesita para correr, sin lo que
# se regenera (archivo de partidas, iconos, cachés) ni lo que es del usuario (datos/,
# salida/, capturas/). `perm-2.json` SÍ va: `coach/conocimiento.py` lo lee al arrancar y
# sin él la app arranca igual pero con menos conocimiento. `perm-3.json` (17 MB) solo lo
# usa una herramienta de minería, y se queda fuera. Después lo **desempaqueta en un directorio temporal y lo arranca**:
# si no responde `/api/estado`, el paquete no sirve y el script falla.
#
# Uso:
#   herramientas/empaquetar.sh                # construye y prueba
#   herramientas/empaquetar.sh --sin-prueba   # solo construye
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
PROBAR=1
[ "${1:-}" = "--sin-prueba" ] && PROBAR=0

# Versión legible: la del CHANGELOG (v0.9) + el commit corto. `git describe` daba
# «baseline-2026-11-09-130-gfe9ba84», que no le dice nada a quien descarga.
VERSION="$(grep -oE '^## v[0-9.]+' CHANGELOG.md 2>/dev/null | head -1 | sed 's/^## //')"
VERSION="${VERSION:-v0.0}"
SHA="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d)"
NOMBRE="abrams-coach-$VERSION-$SHA"
DIST="$RAIZ/dist"
ARCHIVO="$DIST/$NOMBRE.tar.gz"
mkdir -p "$DIST"

EXCLUIR=(
  --exclude=.git --exclude=__pycache__ --exclude='*.pyc'
  --exclude=.cuenta --exclude='.cuenta*'
  --exclude=datos --exclude=salida --exclude=capturas --exclude=grabaciones
  --exclude=informes --exclude=dist --exclude=.pytest_cache
  --exclude=data/archivo --exclude=data/iconos --exclude=data/api_cache
  --exclude=data/demos_cache --exclude=data/replay_actual.json
  --exclude=data/perm-3.json --exclude=data/historico.json.gz
  --exclude=.venv --exclude=venv
)

echo "empaquetando $NOMBRE"
tar czf "$ARCHIVO" "${EXCLUIR[@]}" --transform "s,^\.,$NOMBRE," .
TAM=$(du -h "$ARCHIVO" | cut -f1)
echo "  $ARCHIVO ($TAM)"

# Puerta de privacidad: el paquete se comparte. Nada de la cuenta, la base local, la salida
# ni el historial de git puede ir dentro. Una vez salió `.cuenta` sin que nadie mirara.
# `|| true`: sin coincidencias grep devuelve 1 y `set -e` abortaría el script.
PROHIBIDOS=$(tar tzf "$ARCHIVO" | grep -E '(^|/)(\.cuenta[^/]*|datos/|salida/|\.git/)' | head -5 || true)
if [ -n "$PROHIBIDOS" ]; then
  echo "  FALLA: el paquete trae archivos que no deben salir:" >&2
  echo "$PROHIBIDOS" | sed 's/^/    /' >&2
  rm -f "$ARCHIVO"
  exit 1
fi

if [ "$PROBAR" = "0" ]; then
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "probando el paquete en $TMP"
tar xzf "$ARCHIVO" -C "$TMP"
PUERTO=8098
( cd "$TMP/$NOMBRE" && python3 run.py --fuente simulado --puerto $PUERTO \
    > "$TMP/arranque.log" 2>&1 & echo $! > "$TMP/pid" )
sleep 8
CODIGO=$(curl -s -o "$TMP/estado.json" -w '%{http_code}' --max-time 3 \
         "http://127.0.0.1:$PUERTO/api/estado" || echo 000)
kill "$(cat "$TMP/pid")" 2>/dev/null || true

if [ "$CODIGO" != "200" ]; then
  echo "  FALLA: /api/estado devolvió $CODIGO" >&2
  tail -20 "$TMP/arranque.log" >&2 || true
  exit 1
fi
python3 - "$TMP/estado.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("camino"), "el paquete no trae camino: falta data/"
assert d.get("recomendaciones"), "el paquete no recomienda nada"
print(f"  ok: {len(d['camino'])} ítems de camino y {len(d['recomendaciones'])} recomendaciones")
PY
echo "listo: $ARCHIVO"
