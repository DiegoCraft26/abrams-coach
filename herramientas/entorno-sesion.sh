#!/usr/bin/env bash
# Entorno gráfico para procesos que arranca systemd --user.
#
# Por qué existe: el servicio `abrams-coach-esperar` no hereda DISPLAY ni
# WAYLAND_DISPLAY (systemd no los importa en esta sesión). Sin ellos, `spectacle`
# aborta (SIGABRT) y el coach se queda con "error de lectura" aunque el resto
# funcione.
#
# El 2026-11-15 el panel se abría y moría al instante con
# `Gdk.Display.get_default()` = None: este script elegía el primer socket del
# glob, que puede ser de una sesión anterior. Ahora la fuente de verdad es el
# entorno de systemd --user (lo importa Plasma al entrar) y el socket se
# comprueba antes de exportarlo.
#
# Uso: entorno-sesion.sh <comando> [args...]
set -uo pipefail

: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR

if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi

# 1) Lo que el gestor de sesión ya importó: es lo único que sabemos que es de
#    esta sesión y no de una anterior.
entorno_systemd=""
if command -v systemctl >/dev/null 2>&1; then
  entorno_systemd="$(systemctl --user show-environment 2>/dev/null || true)"
fi

de_systemd() {
  printf '%s\n' "$entorno_systemd" | sed -n "s/^$1=//p" | head -n 1
}

if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  c="$(de_systemd WAYLAND_DISPLAY)"
  if [ -n "$c" ] && [ -S "$XDG_RUNTIME_DIR/$c" ]; then
    export WAYLAND_DISPLAY="$c"
  fi
fi

if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  for s in "$XDG_RUNTIME_DIR"/wayland-[0-9]*; do
    [ -S "$s" ] || continue
    export WAYLAND_DISPLAY="${s##*/}"
    break
  done
fi

if [ -z "${DISPLAY:-}" ]; then
  c="$(de_systemd DISPLAY)"
  [ -n "$c" ] && export DISPLAY="$c"
fi

if [ -z "${DISPLAY:-}" ]; then
  for s in /tmp/.X11-unix/X[0-9]*; do
    [ -S "$s" ] || continue
    export DISPLAY=":${s##*/X}"
    break
  done
fi

export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-$(de_systemd XDG_SESSION_TYPE)}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"

# 2) Sin comprobación de GDK a propósito: dentro del sandbox del agente GDK
#    devuelve None incluso con el entorno correcto, así que un test así
#    aquí daría falsos negativos y impediría abrir el panel. El bucle de
#    reapertura lo corta herramientas/vigilar.py (PANEL_ROTO_S).

exec "$@"
