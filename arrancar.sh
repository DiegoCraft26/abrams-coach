#!/bin/bash
# Arranca el coach en segundo plano y guarda el PID. Nada de autostart: lo abres tú.
cd "$(dirname "$0")"
# La cuenta de Steam no viaja en el repo: se lee de .cuenta (ignorado por git) o de
# ABRAMS_CUENTA. En modo simulado no hace falta.
[ -f .cuenta ] && export ABRAMS_CUENTA="$(tr -d '[:space:]' < .cuenta)"
FUENTE="${1:-simulado}"
PUERTO="${2:-8090}"
LOG=/tmp/abrams-coach.log
# El log se reiniciaba con cada arranque (`>`): el fallo de «a las dos partidas se
# rompe» se perdía al volver a abrir. Ahora se conserva el anterior y se siguen 5.
[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1" && for i in 4 3 2 1; do
  [ -f "$LOG.$i" ] && mv -f "$LOG.$i" "$LOG.$((i+1))"
done
[ -f /tmp/abrams-coach.pid ] && kill "$(cat /tmp/abrams-coach.pid)" 2>/dev/null
sleep 0.5
nohup python3 -u run.py --fuente "$FUENTE" --puerto "$PUERTO" > "$LOG" 2>&1 &
echo $! > /tmp/abrams-coach.pid
echo "arrancado pid $(cat /tmp/abrams-coach.pid) · http://127.0.0.1:$PUERTO · log $LOG"
