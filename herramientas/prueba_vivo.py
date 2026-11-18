#!/usr/bin/env python3
"""Prueba en vivo de una pasada: mide el coach con el juego abierto y deja un informe.

Para qué: la única pieza del proyecto que no se puede verificar sin jugar es el coste real
en partida (¿hay tirón?) y el paso por menú → partida → fin. Este comando lo recoge solo,
sin overlays y sin que nadie mire:

    abrams-coach juego abierto  →  python3 herramientas/prueba_vivo.py --minutos 5

Hace cuatro cosas y las deja escritas en `salida/prueba-vivo-<fecha>.md`:

1. comprueba que Deadlock está corriendo (si no, sale con un mensaje claro);
2. arranca el coach en modo auto si no está ya en el puerto;
3. muestrea GPU, CPU y RAM cada 2 s (CPU por ticks de `/proc`, no el `%CPU` de `ps`);
4. al terminar, resume la fase del juego por la que pasó (menú, partida, cierre) leyendo
   el `console.log`, y cierra el coach si lo arrancó él.

No decide si el resultado es bueno: deja los números y las transiciones. La comparación
con «sin coach» se hace corriendo esto dos veces, una con el coach ya encendido y otra
justo después de apagarlo.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.fuentes import log_juego          # noqa: E402
from coach.nucleo_demo import juego_abierto  # noqa: E402

SALIDA = os.path.join(RAIZ, "salida")


def _gpu_ruta():
    import glob
    for ruta in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        return ruta
    return None


def _gpu():
    ruta = _gpu_ruta()
    try:
        with open(ruta, encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, TypeError, ValueError):
        return None


def _procesos(patron="run.py"):
    """[(pid, ticks, rss_mb)] del coach."""
    hz = os.sysconf("SC_CLK_TCK")
    fuera = []
    for entrada in os.listdir("/proc"):
        if not entrada.isdigit():
            continue
        try:
            with open(f"/proc/{entrada}/cmdline", "rb") as f:
                linea = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
            if patron not in linea or "prueba_vivo" in linea:
                continue
            with open(f"/proc/{entrada}/stat", encoding="ascii") as f:
                campos = f.read().split()
            ticks = int(campos[13]) + int(campos[14])
            with open(f"/proc/{entrada}/statm", encoding="ascii") as f:
                paginas = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        fuera.append((int(entrada), ticks, paginas * os.sysconf("SC_PAGE_SIZE")
                      / 1024 / 1024))
    return fuera, hz


def _coach_responde(puerto=8090):
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/salud",
                                    timeout=2) as r:
            return r.status == 200
    except Exception:                                          # noqa: BLE001
        return False


def muestrear(minutos, puerto):
    muestras = {"gpu": [], "cpu": [], "rss": [], "fases": []}
    previos, t_previo = {}, time.time()
    t0 = t_previo
    fase_prev = None
    while time.time() - t0 < minutos * 60:
        time.sleep(2.0)
        ahora = time.time()
        dt = max(0.001, ahora - t_previo)
        t_previo = ahora
        g = _gpu()
        if g is not None:
            muestras["gpu"].append(g)
        cpu = rss = None
        procesos, hz = _procesos()
        for pid, ticks, esta_rss in procesos:
            antes = previos.get(pid)
            previos[pid] = ticks
            if antes is None:
                continue
            cpu = (cpu or 0.0) + (ticks - antes) / hz / dt * 100.0
            rss = (rss or 0.0) + esta_rss
        if cpu is not None:
            muestras["cpu"].append(cpu)
            if rss:
                muestras["rss"].append(rss)
        estado, frescura = log_juego.estado_ui()
        fase = (estado, log_juego.mapa(), log_juego.cerrado())
        if fase != fase_prev:
            muestras["fases"].append({"t": round(ahora - t0, 1), "estado": estado,
                                      "mapa": fase[1], "cerrado": fase[2],
                                      "frescura_log_s": round(frescura or 0, 1)})
            fase_prev = fase
    return muestras


def _resumen(lista):
    if not lista:
        return None
    return {"mediana": round(statistics.median(lista), 1),
            "p95": round(sorted(lista)[int(len(lista) * 0.95)], 1),
            "max": round(max(lista), 1), "n": len(lista)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=float, default=3.0)
    ap.add_argument("--puerto", type=int, default=8090)
    ap.add_argument("--arrancar", action="store_true",
                    help="arranca el coach si no está corriendo (y lo cierra al acabar)")
    a = ap.parse_args()

    if not juego_abierto(usar_cache=False):
        print("Deadlock no está corriendo. Abre el juego (menú o partida) y repite: "
              "el sentido de esta prueba es medir con el juego vivo.")
        return 2

    propio = False
    if not _coach_responde(a.puerto):
        if not a.arrancar:
            print(f"el coach no responde en :{a.puerto}. Añade --arrancar para que lo "
                  f"levante esta prueba, o abre la app como siempre.")
            return 2
        print("arrancando el coach…", flush=True)
        subprocess.Popen([sys.executable, "-u", "run.py", "--fuente", "auto",
                          "--puerto", str(a.puerto)], cwd=RAIZ,
                         stdout=open("/tmp/prueba-vivo-coach.log", "w"),
                         stderr=subprocess.STDOUT)
        propio = True
        for _ in range(20):
            if _coach_responde(a.puerto):
                break
            time.sleep(0.5)

    print(f"midiendo {a.minutos} min con el juego abierto…", flush=True)
    m = muestrear(a.minutos, a.puerto)
    datos = {"gpu_pct": _resumen(m["gpu"]), "cpu_coach_pct": _resumen(m["cpu"]),
             "rss_mb": _resumen(m["rss"]), "fases": m["fases"]}

    os.makedirs(SALIDA, exist_ok=True)
    ruta = os.path.join(SALIDA, f"prueba-vivo-{time.strftime('%Y%m%d-%H%M')}.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"# Prueba en vivo — {time.strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"Duración: {a.minutos} min · puerto {a.puerto} · "
                f"coach arrancado por la prueba: {'sí' if propio else 'ya estaba'}\n\n")
        for clave, etiqueta in (("gpu_pct", "GPU busy (%)"),
                                ("cpu_coach_pct", "CPU del coach (% de un núcleo)"),
                                ("rss_mb", "RAM del coach (MB)")):
            r = datos[clave]
            f.write(f"- **{etiqueta}**: " + (f"mediana {r['mediana']} · p95 {r['p95']} · "
                                             f"máx {r['max']} (n={r['n']})"
                                             if r else "sin datos") + "\n")
        f.write("\n## Fase del juego durante la prueba\n\n")
        if not m["fases"]:
            f.write("- sin cambios de fase\n")
        for x in m["fases"]:
            f.write(f"- +{x['t']}s: estado={x['estado']} · mapa={x['mapa']} · "
                    f"cerrado={x['cerrado']} · log de hace {x['frescura_log_s']}s\n")
    print(f"informe: {os.path.relpath(ruta, RAIZ)}")
    print(json.dumps({k: v for k, v in datos.items() if k != "fases"},
                     ensure_ascii=False))

    if propio:
        print("cerrando el coach que arrancó esta prueba…")
        for pid, _, _ in _procesos()[0]:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
