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
  echo "Faltan ${#FALTAN[@]} piezas."
  if command -v pacman >/dev/null; then
    echo "  sudo pacman -S --needed ${FALTAN[*]}"
  elif command -v apt >/dev/null; then
    # Traduce los nombres de Arch a los de Debian/Ubuntu.
    declare -A EQUIV=(
      [python3]=python3 [python-gobject]=python3-gi [gtk4]=gir1.2-gtk-4.0
      [python-pillow]=python3-pil [python-numpy]=python3-numpy [python-yaml]=python3-yaml
    )
    apt=(); for paquete in "${FALTAN[@]}"; do apt+=("${EQUIV[$paquete]:-$paquete}"); done
    echo "  sudo apt install ${apt[*]}"
  elif command -v dnf >/dev/null; then
    echo "  sudo dnf install ${FALTAN[*]}    # nombres a revisar en Fedora"
  else
    echo "  instala: ${FALTAN[*]}"
  fi
  echo
  echo "El comando se instala igual; el panel arrancará cuando estén todas."
fi

# Cuenta de Steam opcional: sin ella el modo vivo usa el id de partida del HUD.
if [ ! -f "$BASE/.cuenta" ] && [ -t 0 ]; then
  echo
  read -r -p "SteamID64 para el modo vivo (Enter para omitir, se guarda en .cuenta): " cuenta
  if [ -n "$cuenta" ]; then
    printf '%s\n' "$cuenta" > "$BASE/.cuenta"
    chmod 600 "$BASE/.cuenta"
    echo "  guardada en .cuenta (ignorada por git)"
  fi
fi

mkdir -p "$DESTINO"
ln -sfn "$BASE/herramientas/cli.sh" "$DESTINO/abrams-coach"

# Entrada de menú: deja «Abrams Coach» en el lanzador de aplicaciones. Desde ahí se
# le puede asignar un atajo global en Ajustes → Atajos.
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/abrams-coach.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Abrams Coach
Comment=Panel de decisiones para Deadlock
Exec=$BASE/herramientas/cli.sh abrir
Icon=applications-games
Terminal=false
Categories=Game;
DESKTOP
echo "  menú   Abrams Coach (atajo: Ajustes → Atajos → añadir comando «abrams-coach abrir»)"

# Arranque automático opcional: al iniciar sesión queda esperando a Deadlock.
if [ -t 0 ]; then
  echo
  read -r -p "¿Abrir el panel solo cuando abras Deadlock? [s/N]: " auto
  if [ "${auto,,}" = "s" ] || [ "${auto,,}" = "si" ] || [ "${auto,,}" = "sí" ]; then
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/abrams-coach-esperar.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Abrams Coach (espera)
Comment=Arranca el coach y el panel cuando abres Deadlock
Exec=$BASE/herramientas/cli.sh esperar
Terminal=false
NoDisplay=true
DESKTOP
    echo "  listo  se abrirá solo al jugar (quita ~/.config/autostart/abrams-coach-esperar.desktop para deshacerlo)"
  fi
fi
chmod +x "$BASE/herramientas/cli.sh" "$BASE/herramientas/partida.sh" 2>/dev/null

case ":$PATH:" in
  *":$DESTINO:"*) echo "Listo. Prueba: abrams-coach estado" ;;
  *) echo "Añade $DESTINO al PATH y prueba: abrams-coach estado" ;;
esac
