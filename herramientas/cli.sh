#!/usr/bin/env bash
# Comando único del Abrams Coach.
#
#   abrams-coach demo      panel con datos de ejemplo (sin juego)
#   abrams-coach abrir     abre coach + panel ahora (sin preparar la máquina)
#   abrams-coach jugar     prepara la máquina y abre coach + panel
#   abrams-coach estado    qué corre, RAM, VRAM y última lectura
#   abrams-coach archivar  importa la sesión a la base local (+resultados)
#   abrams-coach informe   resumen de la última partida archivada
#   abrams-coach nota      las tres reglas de la última partida (3200, muertes, participación)
#   abrams-coach plan      qué atacar hoy según tus últimas ranked
#   abrams-coach sesion    cómo fue la sesión, desde las notas archivadas
#   abrams-coach listo     chequeo previo: cuenta, red, captura, overlay, puerto, disco
#   abrams-coach ayuda     el ciclo de una sesión, en una pantalla
#   abrams-coach esperar   arranca solo cuando abres Deadlock y archiva al salir
#                          (el overlay encima del HUD es opt-in: `esperar --overlay`)
#   abrams-coach api       prueba la partida en vivo por HTTP (sin visión, sin capturas)
#   abrams-coach medir     mide la cadena de latencia
#   abrams-coach linea     rejuega una partida real minuto a minuto (qué recomienda)
#   abrams-coach banco     corre el motor sobre todas las partidas y saca sesgos
#   abrams-coach meta      recalcula el meta observado de Abrams desde el cache
#   abrams-coach tesoros   combinaciones raras que ganan (API, por parche)
#   abrams-coach resultado guarda el resultado (win/loss) de una partida
#   abrams-coach variantes composiciones que se repiten y cómo te fue (archivo local)
#   abrams-coach historico índice de composiciones: construirlo y consultarlo
#   abrams-coach items     qué compran los que ganan contra una comp
#   abrams-coach camino    camino de compra de un héroe desde sus partidas
#   abrams-coach archivo   baja partidas públicas al archivo local
#   abrams-coach impacto   mide GPU/CPU/RAM del coach sin overlays
#   abrams-coach verificar comprueba que las piezas de la v2 están en pie
#   abrams-coach prueba    mide el coach con el juego abierto y deja un informe
#   abrams-coach menu      comprueba la app con el juego en el menú (sin partida)
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
    # Igual que `abrir`: la ventana manda y al cerrarla se apaga el coach de ejemplo,
    # para no dejar la unidad «Abrams Coach» viva en segundo plano.
    trap 'kill "$(cat /tmp/abrams-coach.pid 2>/dev/null)" 2>/dev/null; rm -f /tmp/abrams-coach.pid' EXIT INT TERM HUP
    "$PY" panel_nativo.py
    exit 0
    ;;
  jugar|abrir)
    # `prep pegado` abre el coach y el panel, y lo coloca en el monitor secundario.
    # Antes se ejecutaba otro panel aquí: salían dos ventanas.
    # `pegado`: la ventana del panel es el proceso principal; al cerrarla se apaga
    # el coach (antes quedaba vivo como unidad systemd para siempre).
    # `ABRAMS_QUEDAR=1` mantiene el comportamiento viejo (todo en segundo plano).
    [ "${ABRAMS_QUEDAR:-0}" = "1" ] && exec ./herramientas/partida.sh prep
    exec ./herramientas/partida.sh prep pegado
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
    # Modo del motor de valor por ítem: MEDIDO o CIEGO, con el motivo. Sin esto, el
    # estado se veía completo mientras el panel no tenía evidencia que enseñar.
    "$PY" - <<'PYMODO'
import sys
sys.path.insert(0, ".")
try:
    from coach import valor
    modo = valor.modo()
    motivo = valor._cache.get("error") or ""
    print(f"motor v2: {modo}" + (f" · {motivo}" if modo == "CIEGO" and motivo else ""))
except Exception as exc:
    print(f"motor v2: no se pudo consultar ({exc})")
PYMODO
    ;;
  archivar)
    shift
    # El archivado no se toca: si sale bien, se intenta además cerrar el resultado
    # (red puede fallar; `|| true` para no romper el archivado por eso).
    # Se propaga --db al paso de resultados: antes el archivado iba a una base y los
    # resultados a otra (visto en la prueba con base temporal).
    db=""
    anterior=""
    for arg in "$@"; do
      case "$anterior" in --db) db="$arg" ;; esac
      case "$arg" in --db=*) db="${arg#--db=}" ;; esac
      anterior="$arg"
    done
    "$PY" herramientas/archivar.py "$@"
    rc=$?
    if [ $rc -eq 0 ]; then
      if [ -n "$db" ]; then
        "$PY" herramientas/registrar_resultado.py --todas --limite 10 --db "$db" || true
      else
        "$PY" herramientas/registrar_resultado.py --todas --limite 10 || true
      fi
    fi
    exit $rc
    ;;
  informe)
    shift
    exec "$PY" herramientas/informe_partida.py "$@"
    ;;
  nota)
    shift
    exec "$PY" herramientas/demos/nota.py "$@"
    ;;
  plan)
    shift
    exec "$PY" herramientas/demos/plan.py "$@"
    ;;
  sesion)
    shift
    exec "$PY" herramientas/demos/sesion.py "$@"
    ;;
  listo)
    shift
    exec "$PY" herramientas/listo.py "$@"
    ;;
  ayuda|--ayuda|-h|--help)
    cat <<'AYUDA'
Abrams Coach · el ciclo de una sesión

  Antes de encolar
    abrams-coach listo        revisa cuenta, red, captura, overlay, puerto y disco
    abrams-coach plan         qué atacar hoy, con tu referencia de banda y un objetivo

  Durante la partida
    abrams-coach esperar      abre coach y panel solo cuando abres Deadlock
    abrams-coach esperar --overlay   igual, y además la tarjeta encima del HUD

  Al terminar cada partida
    abrams-coach nota         las reglas de la última partida (sale sola al cerrar el juego)

  Al cerrar el día
    abrams-coach sesion       cuántas partidas, cómo fuiste y qué regla se te fue

  Diagnóstico
    abrams-coach estado       qué corre, RAM/GPU, modo del motor
    abrams-coach verificar    piezas del sistema, una por una
    abrams-coach parar        cierra coach, panel y grabadora

  Lo que el coach NO hace: recomendar ítems por «valor medido» (se probó con 20 parches
  y ningún ítem pasó), leer memoria del juego, ni saber tu oro exacto al instante.
  Detalle: docs/MOTOR-V2.md · docs/USO-DIARIO.md
AYUDA
    ;;
  api)
    exec "$PY" herramientas/probar_vivo.py "$@"
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
  linea)
    shift
    exec "$PY" herramientas/linea_tiempo.py "$@"
    ;;
  banco)
    shift
    exec "$PY" herramientas/banco_partidas.py "$@"
    ;;
  meta)
    shift
    exec "$PY" herramientas/meta_abrams.py "$@"
    ;;
  tesoros)
    shift
    exec "$PY" herramientas/tesoros.py "$@"
    ;;
  resultado)
    shift
    exec "$PY" herramientas/registrar_resultado.py "$@"
    ;;
  variantes)
    shift
    exec "$PY" herramientas/variantes.py "$@"
    ;;
  historico)
    shift
    exec "$PY" herramientas/historico.py "$@"
    ;;
  items)
    shift
    exec "$PY" herramientas/items_comp.py "$@"
    ;;
  camino)
    shift
    exec "$PY" herramientas/camino_heroe.py "$@"
    ;;
  archivo)
    shift
    exec "$PY" herramientas/archivo_abrams.py "$@"
    ;;
  impacto)
    shift
    exec "$PY" herramientas/medir_impacto.py "$@"
    ;;
  verificar)
    shift
    exec "$PY" herramientas/verificar_v2.py "$@"
    ;;
  prueba)
    shift
    exec "$PY" herramientas/prueba_vivo.py "$@"
    ;;
  menu)
    shift
    exec "$PY" herramientas/prueba_menu.py "$@"
    ;;
  parar)
    ./herramientas/partida.sh fin
    ;;
  *)
    sed -n '/^#   abrams-coach/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
