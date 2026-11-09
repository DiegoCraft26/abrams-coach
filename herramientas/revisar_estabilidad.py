#!/usr/bin/env python3
"""¿Está sano el coach ahora mismo? Comprobación de estabilidad en cinco segundos.

Responde a los criterios de la Fase 0 sin tener que leer logs a mano: servicio vivo y
desde cuándo, reinicios de hoy, panel vivo y su último final (limpio, señal o excepción),
coach publicando datos frescos y si está fingiendo una partida.

Uso:
    python3 herramientas/revisar_estabilidad.py
    python3 herramientas/revisar_estabilidad.py --json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

SERVICIO = "abrams-coach-esperar"
CRASH_PANEL = "/tmp/abrams-panel-crash.log"
PUERTO = 8090


def _sh(*orden, timeout=5):
    try:
        return subprocess.run(list(orden), capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def estado_servicio() -> dict:
    activo = _sh("systemctl", "--user", "is-active", SERVICIO)
    desde = _sh("systemctl", "--user", "show", "-p", "ActiveEnterTimestamp",
                "--value", SERVICIO)
    reinicios = _sh("journalctl", "--user", "-u", SERVICIO, "--since", "today",
                    "--no-pager")
    return {
        "activo": activo == "active",
        "desde": desde,
        "reinicios_hoy": len(re.findall(r"Scheduled restart", reinicios or "")),
    }


def procesos(salida: str | None = None) -> dict:
    """Busca coach y panel en la lista de procesos.

    Se lee la línea por tokens en vez de con una expresión regular grande: la salida de
    `ps` cambia de formato con las columnas, y una primera versión con regex no vio un
    coach que estaba corriendo (decía «no corre» con el coach vivo).
    """
    if salida is None:
        salida = _sh("ps", "-eo", "etime,args")
    coach = panel = None
    for linea in (salida or "").splitlines():
        partes = linea.split()
        if not partes:
            continue
        interprete = next((i for i, p in enumerate(partes) if p.startswith("python")),
                          None)
        if interprete is None or interprete == 0:
            continue
        uptime = partes[interprete - 1]
        if any(p.endswith("panel_nativo.py") for p in partes):
            panel = uptime
        elif any(p.endswith("run.py") for p in partes):
            coach = uptime
    return {"coach": coach is not None, "coach_uptime": coach,
            "panel": panel is not None, "panel_uptime": panel}


def final_del_panel(ruta=CRASH_PANEL) -> list[str]:
    """Los últimos finales del panel: es lo que antes no existía."""
    try:
        with open(ruta, encoding="utf-8") as f:
            lineas = [l.strip() for l in f if l.strip()]
    except OSError:
        return []
    return [re.sub(r"^.*?\[pid \d+\] ", "", l) for l in lineas[-4:]]


def estado_coach(puerto=PUERTO) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/estado",
                                    timeout=4) as r:
            return json.loads(r.read().decode())
    except Exception:                                     # noqa: BLE001
        return {}


def revisar() -> dict:
    srv = estado_servicio()
    pro = procesos()
    coach = estado_coach()
    edad = coach.get("edad_s")
    fuente = coach.get("fuente")
    avisos = []
    if not srv["activo"] and not pro["coach"]:
        avisos.append("no hay coach ni servicio: la app está apagada")
    if pro["coach"] and coach and fuente == "apertura" and (coach.get("t") or 0) == 0:
        avisos.append("el coach solo publica el plan de apertura: no ve la partida")
    if isinstance(edad, (int, float)) and edad > 60:
        avisos.append(f"el coach lleva {int(edad)} s sin publicar nada")
    if pro["panel"] is False and pro["coach"]:
        avisos.append("el coach corre sin panel")
    return {
        "servicio": srv, "procesos": pro,
        "coach": {"fuente": fuente, "t": coach.get("t"), "edad_s": edad,
                  "listo": coach.get("listo"),
                  "solo_reloj": coach.get("solo_reloj"),
                  "slots": coach.get("slots")},
        "panel_ultimos_finales": final_del_panel(),
        "avisos": avisos,
        "sano": not avisos,
        "cuando": time.strftime("%H:%M:%S"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    datos = revisar()
    if a.json:
        print(json.dumps(datos, ensure_ascii=False, indent=1))
        return 0 if datos["sano"] else 1

    srv, pro = datos["servicio"], datos["procesos"]
    print(f"Abrams Coach · estabilidad a las {datos['cuando']}")
    print(f"  servicio   {'activo desde ' + srv['desde'] if srv['activo'] else 'parado'}"
          f" · {srv['reinicios_hoy']} reinicios hoy")
    print(f"  coach      {'corriendo hace ' + (pro['coach_uptime'] or '?') if pro['coach'] else 'no corre'}"
          f" · fuente {datos['coach']['fuente'] or '—'} · t {datos['coach']['t']}"
          f" · edad {datos['coach']['edad_s']}")
    print(f"  panel      {'corriendo hace ' + (pro['panel_uptime'] or '?') if pro['panel'] else 'no corre'}")
    if datos["panel_ultimos_finales"]:
        print("  finales    " + " | ".join(datos["panel_ultimos_finales"][-3:]))
    if datos["avisos"]:
        for aviso in datos["avisos"]:
            print(f"  aviso      {aviso}")
    else:
        print("  veredicto  sano: nada que corregir")
    return 0 if datos["sano"] else 1


if __name__ == "__main__":
    sys.exit(main())
