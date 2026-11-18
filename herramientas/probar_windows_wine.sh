#!/usr/bin/env bash
# Corre el código de Windows bajo Wine, con el Python embebido de python.org.
#
# Por qué: sin una máquina Windows, el overlay Win32 y la captura DXGI eran «leído pero
# nunca ejecutado». Con Wine se ejecutan de verdad las llamadas de Win32 (user32, gdi32):
# registrar clase, crear ventana, UpdateLayeredWindow, destruir. No sustituye a probar en
# Windows (falta DXGI de verdad y el compositor), pero caza cosas como `WNDCLASSW`, que
# `ctypes.wintypes` no trae, o un HWND truncado por falta de `restype`.
#
# Uso:
#   herramientas/probar_windows_wine.sh
#
# Requisitos: wine y curl. Si falta wine, sale con 0 diciendo que se omitió.
set -uo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_WIN="python-3.12.7-embed-amd64"
URL="https://www.python.org/ftp/python/3.12.7/${PY_WIN}.zip"
BASE="${TMPDIR:-/tmp}/abrams-wine"
PREFIJO="$BASE/wineprefix"
PYDIR="$BASE/py"

if ! command -v wine >/dev/null 2>&1; then
  echo "wine no está instalado: se omite la prueba de Windows"
  exit 0
fi

mkdir -p "$BASE" && chmod 700 "$BASE" "$PREFIJO" 2>/dev/null || true
mkdir -p "$PREFIJO"

if [ ! -f "$PYDIR/python.exe" ]; then
  echo "descargando Python embebido de Windows…"
  curl -sL -o "$BASE/py.zip" "$URL" || { echo "no se pudo descargar"; exit 2; }
  mkdir -p "$PYDIR"
  unzip -q "$BASE/py.zip" -d "$PYDIR"
fi

# Dependencias de Python para Windows (mss + Pillow). Si no hay `uv`, se corre solo la
# parte del overlay: la captura se declarará no disponible, que también es un caso válido.
if command -v uv >/dev/null 2>&1 && [ ! -d "$PYDIR/mss" ]; then
  echo "instalando mss y Pillow para Windows…"
  uv pip install --quiet --target "$BASE/deps" --no-deps \
    --python-version 3.12 --python-platform windows mss "pillow==11.0.0" 2>/dev/null || true
  [ -d "$BASE/deps/mss" ] && cp -r "$BASE/deps/mss" "$PYDIR/"
  [ -d "$BASE/deps/PIL" ] && cp -r "$BASE/deps/PIL" "$PYDIR/"
fi

cp "$RAIZ/coach/ui/overlay_windows.py" "$RAIZ/coach/fuentes/captura_windows.py" \
   "$RAIZ/herramientas/wine_prueba_windows.py" "$PYDIR/"

export WINEPREFIX="$PREFIJO" WINEDEBUG=-all DISPLAY="${DISPLAY:-:0}" PYTHONIOENCODING=utf-8
cd "$PYDIR" || exit 2
# Wine inicializa el prefijo la primera vez; se tolera el ruido de arranque.
wine python.exe wine_prueba_windows.py 2> >(grep -v -E "fixme|wine: " >&2) | tee "$BASE/salida.txt"
grep -q "todo ok" "$BASE/salida.txt"
