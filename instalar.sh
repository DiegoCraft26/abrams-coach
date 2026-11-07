#!/usr/bin/env bash
# Comprueba dependencias y deja el comando `abrams-coach` en el PATH del usuario.
# No instala nada y no usa sudo: si falta algo, dice qué y cómo ponerlo.
set -uo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTINO="${XDG_BIN_HOME:-$HOME/.local/bin}"
FALTAN=()

ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
falta(){ printf '  \033[31mfalta\033[0m %s\n' "$1"; FALTAN+=("$2"); }

echo "Abrams Coach · comprobación del entorno"

if command -v python3 >/dev/null; then
  ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    ok "python3 $ver"
  else
    falta "python3 $ver (hace falta 3.11 o más)" "python3"
  fi
else
  falta "python3" "python3"
fi

python3 -c "import gi" 2>/dev/null && ok "PyGObject (gtk4)" || falta "PyGObject" "python-gobject"
python3 -c "
import gi; gi.require_version('Gtk','4.0')
from gi.repository import Gtk" 2>/dev/null && ok "GTK 4" || falta "GTK 4" "gtk4"
python3 -c "import PIL" 2>/dev/null && ok "Pillow" || falta "Pillow" "python-pillow"
python3 -c "import numpy" 2>/dev/null && ok "NumPy" || falta "NumPy" "python-numpy"
python3 -c "import yaml" 2>/dev/null && ok "PyYAML" || falta "PyYAML" "python-yaml"

command -v tesseract >/dev/null && ok "tesseract $(tesseract --version 2>&1 | head -1 | awk '{print $2}')" \
  || falta "tesseract" "tesseract"
command -v spectacle  >/dev/null && ok "spectacle" || falta "spectacle" "spectacle"
command -v sqlite3    >/dev/null && ok "sqlite3"   || falta "sqlite3" "sqlite"

echo
if [ ${#FALTAN[@]} -gt 0 ]; then
  echo "Faltan ${#FALTAN[@]} piezas. En CachyOS/Arch:"
  echo "  sudo pacman -S --needed ${FALTAN[*]}"
  echo
  echo "El comando se instala igual; el panel arrancará cuando estén todas."
fi

mkdir -p "$DESTINO"
ln -sfn "$BASE/herramientas/cli.sh" "$DESTINO/abrams-coach"
chmod +x "$BASE/herramientas/cli.sh" "$BASE/herramientas/partida.sh" 2>/dev/null

case ":$PATH:" in
  *":$DESTINO:"*) echo "Listo. Prueba: abrams-coach estado" ;;
  *) echo "Añade $DESTINO al PATH y prueba: abrams-coach estado" ;;
esac
