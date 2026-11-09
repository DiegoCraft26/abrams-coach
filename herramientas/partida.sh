#!/usr/bin/env bash
# partida.sh — deja la PC lista y graba una partida de Deadlock.
#
#   ./partida.sh prep      apaga lo que roba VRAM, abre coach + panel
#   ./partida.sh grabar    empieza a grabar DP-2 (1440p60 HEVC)
#   ./partida.sh cortar    termina la grabación y dice tamaño/duración
#   ./partida.sh estado    RAM, VRAM, GPU, servicios y estado del coach
#   ./partida.sh fin       cierra grabación, panel y coach
#   ./partida.sh analizar <archivo.mp4>   saca 1 fotograma cada 5 s
#
# No toca el juego: gpu-screen-recorder lee el framebuffer por KMS, no inyecta nada.

set -uo pipefail

BASE="$HOME/Desktop/Chat/abrams-coach"
PUERTO=8090
GRAB="$BASE/grabaciones"
PID_COACH=/tmp/abrams-coach.pid
PID_PANEL=/tmp/abrams-panel.pid
PID_GSR=/tmp/abrams-gsr.pid
OUT_GSR=/tmp/abrams-gsr.out
LOG_COACH=/tmp/abrams-coach.log
LOG_GSR=/tmp/abrams-gsr.log

vram_usada() { awk '{printf "%.2f", $1/1073741824}' /sys/class/drm/card1/device/mem_info_vram_used; }
vram_total() { awk '{printf "%.2f", $1/1073741824}' /sys/class/drm/card1/device/mem_info_vram_total; }
gpu_busy()   { cat /sys/class/drm/card1/device/gpu_busy_percent 2>/dev/null || echo "?"; }
gpu_temp()   { awk '{printf "%.0f", $1/1000}' /sys/class/drm/card1/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1; }

vivo() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

estado() {
  echo "== RAM =="
  free -h | awk 'NR<=2'
  echo
  echo "== GPU =="
  echo "VRAM: $(vram_usada) / $(vram_total) GiB · busy $(gpu_busy)% · $(gpu_temp) °C"
  echo
  echo "== Servicios =="
  for u in dsh-buffer-pantalla llama-server ia-local-guard gamemoded; do
    printf '%-24s %s\n' "$u" "$(systemctl --user is-active "$u" 2>/dev/null || true)"
  done
  echo
  echo "== Grabación =="
  if vivo "$PID_GSR"; then
    echo "grabando → $(cat "$OUT_GSR" 2>/dev/null)"
  else
    echo "detenida"
  fi
  echo
  echo "== Coach =="
  curl -s --max-time 3 "http://127.0.0.1:$PUERTO/api/estado" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("listo:",d.get("listo"),"|",d.get("mensaje") or d.get("estado",{}).get("estado",""))' \
    2>/dev/null || echo "sin respuesta en :$PUERTO"
}

prep() {
  # 1. Lo que roba VRAM o CPU durante el juego.
  systemctl --user stop dsh-buffer-pantalla.service 2>/dev/null || true
  systemctl --user stop llama-server.service 2>/dev/null || true
  command -v gamemoded >/dev/null && systemctl --user start gamemoded.service 2>/dev/null || true

  # 2. Aviso si la RAM no alcanza (no bloquea: el usuario decide).
  local libre
  libre=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  if [ "${libre:-0}" -lt 5000 ]; then
    echo "AVISO: solo ${libre} MB de RAM disponible; cierra Brave/Spotify si el juego tironea."
  fi

  # 3. Coach en vivo (API, sin OCR y sin VRAM) + panel nativo.
  if ! vivo "$PID_COACH"; then
    ( cd "$BASE" && exec nohup python3 run.py --fuente vivo --puerto "$PUERTO" \
        >"$LOG_COACH" 2>&1 ) &
    echo $! >"$PID_COACH"
    sleep 2
  fi
  if ! vivo "$PID_PANEL"; then
    ( cd "$BASE" && exec nohup python3 panel_nativo.py --url "http://127.0.0.1:$PUERTO" \
        >/tmp/abrams-panel.log 2>&1 ) &
    echo $! >"$PID_PANEL"
    sleep 2
  fi

  # El panel nace donde KWin quiere (Wayland no deja colocarse solo): se le pide al
  # compositor que lo mueva al monitor secundario. Si no se puede, no es fatal.
  python3 "$BASE/herramientas/colocar_panel.py" >/dev/null 2>&1 || true

  echo "Coach:  http://127.0.0.1:$PUERTO  (log $LOG_COACH)"
  echo "Panel abierto en el monitor secundario."
  echo
  estado
}

grabar() {
  mkdir -p "$GRAB"
  if vivo "$PID_GSR"; then
    echo "Ya está grabando: $(cat "$OUT_GSR")"
    return 0
  fi
  local out="$GRAB/partida-$(date +%Y%m%d-%H%M%S).mp4"
  nohup gpu-screen-recorder -w DP-2 -f 60 -k hevc -q medium -o "$out" \
    >"$LOG_GSR" 2>&1 &
  echo $! >"$PID_GSR"
  echo "$out" >"$OUT_GSR"
  sleep 2
  if vivo "$PID_GSR"; then
    echo "Grabando → $out"
  else
    echo "Falló el grabador; revisa $LOG_GSR"
    tail -5 "$LOG_GSR"
  fi
}

cortar() {
  if ! vivo "$PID_GSR"; then
    echo "No hay grabación en curso."
    return 0
  fi
  local pid out
  pid=$(cat "$PID_GSR"); out=$(cat "$OUT_GSR")
  kill -INT "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  kill -TERM "$pid" 2>/dev/null || true
  rm -f "$PID_GSR"
  if [ -f "$out" ]; then
    echo "Guardado: $out"
    ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$out" \
      | awk -F= '/duration/{printf "duración: %.0f s\n",$2} /size/{printf "tamaño: %.0f MB\n",$2/1048576}'
  else
    echo "No se creó el archivo; revisa $LOG_GSR"
  fi
}

seguir() {
  local id="${1:-}" cuenta="${2:-}"
  [ -n "$id" ] || { echo "Uso: $0 seguir <match_id> [cuenta]"; return 1; }
  if vivo "$PID_COACH"; then kill "$(cat "$PID_COACH")" 2>/dev/null || true; rm -f "$PID_COACH"; fi
  sleep 1
  local args=(--fuente vivo --match "$id" --puerto "$PUERTO")
  [ -n "$cuenta" ] && args+=(--cuenta "$cuenta")
  ( cd "$BASE" && exec nohup python3 run.py "${args[@]}" >"$LOG_COACH" 2>&1 ) &
  echo $! >"$PID_COACH"
  sleep 3
  echo "Coach fijado a la partida $id${cuenta:+ (cuenta $cuenta)}"
}

fin() {
  cortar
  # Al terminar la partida se archiva sola (bandera `archivado_auto` en
  # config/coach.yaml). Si falla, se avisa y no se pierde la grabación.
  if python3 -c "import sys; sys.path.insert(0,'$BASE'); from coach.config import cargar; sys.exit(0 if cargar().flags.get('archivado_auto', True) else 1)" 2>/dev/null; then
    echo "Archivando partida en datos/coach.db…"
    if archivar; then
      # El informe se genera solo: sin teclado, como el resto de la app.
      python3 "$BASE/herramientas/informe_partida.py" --ultimas 1 >/dev/null 2>&1 \
        && echo "Informe: informes/partidas/ (la última partida)"
    else
      echo "AVISO: el archivado falló; los .jsonl siguen en salida/"
    fi
  fi
  for f in "$PID_PANEL" "$PID_COACH"; do
    if vivo "$f"; then kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; fi
  done
  echo "Panel y coach cerrados."
}

analizar() {
  local src="${1:-}"
  [ -f "$src" ] || { echo "Uso: $0 analizar <archivo.mp4>"; return 1; }
  local name dir
  name=$(basename "$src" .mp4)
  dir="$BASE/analisis/$name"
  mkdir -p "$dir"
  ffmpeg -hide_banner -loglevel error -i "$src" \
    -vf "fps=1/5,scale=1280:-1" -q:v 3 "$dir/f_%04d.jpg"
  echo "Fotogramas en $dir ($(find "$dir" -name 'f_*.jpg' | wc -l) imágenes, 1 cada 5 s)."
}

archivar() {
  # Importa lo ya grabado (decisiones, monitores, compras y videos) a SQLite.
  # Es idempotente: correrlo dos veces no duplica filas.
  python3 "$BASE/herramientas/archivar.py" "$@"
}

resumen() {
  local f="$BASE/salida/decisiones.jsonl"
  [ -s "$f" ] || { echo "Sin decisiones registradas todavía."; return 0; }
  python3 - "$f" <<'PY'
import json, sys, collections
filas = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
t = [f["t"] for f in filas if isinstance(f.get("t"), (int, float))]
print(f"filas: {len(filas)}" + (f" · ventana: {min(t):.0f}s–{max(t):.0f}s" if t else ""))
est = collections.Counter(f.get("estado") for f in filas if f.get("estado"))
print("estados:", ", ".join(f"{k} {v}" for k, v in est.most_common()))
rec = collections.Counter(x for f in filas for x in (f.get("recomendado") or []))
print("recomendados:", ", ".join(f"{k} ({v})" for k, v in rec.most_common(6)))
print(f"filas sin almas: {sum(1 for f in filas if f.get('almas') is None)}/{len(filas)}")
PY
}

case "${1:-estado}" in
  prep)     prep ;;
  grabar)   grabar ;;
  cortar)   cortar ;;
  estado)   estado ;;
  resumen)  resumen ;;
  archivar) shift; archivar "$@" ;;
  seguir)   shift; seguir "${1:-}" "${2:-}" ;;
  fin)      fin ;;
  analizar) shift; analizar "${1:-}" ;;
  *) echo "Uso: $0 {prep|grabar|cortar|estado|resumen|archivar|seguir <match> [cuenta]|fin|analizar <mp4>}"; exit 1 ;;
esac
