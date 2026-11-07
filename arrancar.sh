#!/bin/bash
# Arranca el coach en segundo plano y guarda el PID.
cd "$(dirname "$0")"
FUENTE="${1:-simulado}"
PUERTO="${2:-8090}"
[ -f /tmp/abrams-coach.pid ] && kill "$(cat /tmp/abrams-coach.pid)" 2>/dev/null
sleep 0.5
nohup python3 run.py --fuente "$FUENTE" --puerto "$PUERTO" > /tmp/abrams-coach.log 2>&1 &
echo $! > /tmp/abrams-coach.pid
echo "arrancado pid $(cat /tmp/abrams-coach.pid) · http://127.0.0.1:$PUERTO"
