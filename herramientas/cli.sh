#!/usr/bin/env bash
# Comando único del Abrams Coach.
#
#   abrams-coach demo      panel con datos de ejemplo (sin juego)
#   abrams-coach jugar     prepara la máquina y abre coach + panel
#   abrams-coach estado    qué corre, RAM, VRAM y última lectura
#   abrams-coach archivar  importa la sesión a la base local
#   abrams-coach informe   resumen de la última partida archivada
#   abrams-coach esperar   arranca solo cuando abres Deadlock y archiva al salir
#   abrams-coach medir     mide la cadena de latencia
#   abrams-coach parar     cierra coach, panel y grabadora
set -uo pipefail

# Se invoca por un enlace simbólico en ~/.local/bin: hay que resolverlo antes de
# calcular la raíz, o BASE apunta a ~/.local.
FUENTE="$(readlink -f "${BASH_SOURCE[0]}")"
BASE="$(cd "$(dirname "$FUENTE")/.." && pwd)"
cd "$BASE" || exit 1
PY="python3"

case "${1:-estado}" in
  demo)
    ./arrancar.sh simulado
    sleep 1
    ( sleep 2; "$PY" herramientas/colocar_panel.py >/dev/null 2>&1 || true ) &
    exec "$PY" panel_nativo.py
    ;;
  jugar)
    # `prep` ya abre el coach y el panel, y lo coloca en el monitor secundario.
    # Antes se ejecutaba otro panel aquí: salían dos ventanas.
    exec ./herramientas/partida.sh prep
    ;;
  estado)
    ./herramientas/partida.sh estado
    echo
    "$PY" - <<'PY'
import json, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8090/api/estado", timeout=2) as r:
        d = json.load(r)
except Exception:
    print("panel: sin respuesta (¿está corriendo `abrams-coach demo` o `jugar`?)")
else:
    print(f"panel: t={int(d.get('t') or 0)}s · almas={d.get('almas')} · "
          f"oro={d.get('oro')} · fuente={d.get('fuente')} · edad={d.get('edad_s')}s")
    top = (d.get("recomendaciones") or [{}])[0]
    if top:
        print(f"recomendado: {top.get('name') or top.get('nombre')} "
              f"({top.get('costo')}) · {len(top.get('razones') or [])} razones")
    lat = d.get("latencia") or {}
    if lat:
        print(f"latencia: captura {lat.get('captura_ms')} ms · lectura "
              f"{lat.get('lectura_ms')} ms · TV {lat.get('broadcast_s')} s")
PY
    ;;
  archivar)
    shift
    exec "$PY" herramientas/archivar.py "$@"
    ;;
  informe)
    shift
    exec "$PY" herramientas/informe_partida.py "$@"
    ;;
  medir)
    shift
    exec "$PY" herramientas/medir_latencia.py "$@"
    ;;
  esperar)
    shift
    exec "$PY" herramientas/vigilar.py "$@"
    ;;
  capturas)
    shift
    exec "$PY" herramientas/capturar_ui.py "$@"
    ;;
  parar)
    ./herramientas/partida.sh fin
    ;;
  *)
    sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
