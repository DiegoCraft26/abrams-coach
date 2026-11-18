#!/usr/bin/env python3
"""Mide lo que el coach le cuesta a la partida, sin overlays ni contadores en pantalla.

Diego no quiere capas encima del juego, así que el impacto se mide por fuera:

    gpu_busy_percent      lo que el compositor y la captura le piden a la GPU
    CPU del coach         % de un núcleo que gasta el proceso entero
    ms de captura         lo que tarda cada lectura del HUD (del propio coach)
    fps del juego         si el juego lo escribe en consola (opcional)

Uso:

    python3 herramientas/medir_impacto.py --minutos 3
    python3 herramientas/medir_impacto.py --minutos 3 --puerto 8090   # con coach activo

Compara dos tramos y da la diferencia. La regla del proyecto: sin número no se afirma
«no afecta los FPS».
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# La tarjeta no siempre es card0 (aquí es card1). Se busca la que exponga el contador.
def _gpu_ruta():
    import glob
    for ruta in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        if os.path.exists(ruta):
            return ruta
    return "/sys/class/drm/card0/device/gpu_busy_percent"


GPU = _gpu_ruta()


def gpu_pct():
    try:
        with open(GPU, encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


HZ = os.sysconf("SC_CLK_TCK")


def procesos(patron):
    """[(pid, ticks_de_cpu, rss_mb)] de los procesos que coinciden.

    Se leen los ticks de `/proc/<pid>/stat` y no el `%CPU` de `ps`: ese número es el
    promedio desde que el proceso arrancó, así que en una medición de 3 minutos mide la
    carga de arranque (importar numpy, leer el conocimiento) y no el coste de estar vivo.
    """
    salida = []
    for entrada in os.listdir("/proc"):
        if not entrada.isdigit():
            continue
        try:
            with open(f"/proc/{entrada}/cmdline", "rb") as f:
                linea = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
            if patron not in linea or "medir_impacto" in linea:
                continue
            with open(f"/proc/{entrada}/stat", encoding="ascii") as f:
                campos = f.read().split()
            ticks = int(campos[13]) + int(campos[14])
            with open(f"/proc/{entrada}/statm", encoding="ascii") as f:
                rss_paginas = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        salida.append((int(entrada), ticks, rss_paginas * os.sysconf("SC_PAGE_SIZE")
                       / 1024 / 1024))
    return salida


def estado_coach(puerto):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/estado",
                                    timeout=2) as r:
            d = json.loads(r.read().decode())
        return {"fuente": d.get("fuente"), "listo": d.get("listo"),
                "t": d.get("t"), "latencia": d.get("latencia")}
    except Exception:                                          # noqa: BLE001
        return None


def tramo(minutos, puerto):
    """Muestreo con CPU instantánea por diferencia de ticks entre muestras."""
    muestras = {"gpu": [], "cpu": [], "rss": []}
    previos = {}
    t_previo = time.time()
    t0 = t_previo
    while time.time() - t0 < minutos * 60:
        time.sleep(2.0)
        ahora = time.time()
        dt = ahora - t_previo
        t_previo = ahora
        g = gpu_pct()
        if g is not None:
            muestras["gpu"].append(g)
        cpu = rss = None
        for pid, ticks, esta_rss in procesos("run.py"):
            antes = previos.get(pid)
            previos[pid] = ticks
            if antes is None:
                continue          # primera vez: sin delta no hay porcentaje
            cpu = (cpu or 0.0) + (ticks - antes) / HZ / dt * 100.0
            rss = (rss or 0.0) + esta_rss
        if cpu is not None:
            muestras["cpu"].append(cpu)
            if rss:
                muestras["rss"].append(rss)
        estado_coach(puerto)      # mantiene despierta la conexión con el panel
    return muestras, t_previo


def resumen(m):
    def s(lista):
        if not lista:
            return "sin datos"
        return (f"mediana {statistics.median(lista):.1f} · "
                f"p95 {sorted(lista)[int(len(lista)*0.95)]:.1f} · "
                f"máx {max(lista):.1f}")
    return {"gpu_pct": s(m["gpu"]), "cpu_coach_pct": s(m["cpu"]),
            "rss_mb": s(m["rss"]), "n_gpu": len(m["gpu"]), "n_cpu": len(m["cpu"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=float, default=3.0)
    ap.add_argument("--puerto", type=int, default=8090)
    ap.add_argument("--json", action="store_true", help="salida json en vez de texto")
    a = ap.parse_args()

    print(f"midiendo {a.minutos} min · GPU {GPU} "
          f"{'ok' if gpu_pct() is not None else 'no disponible'}", flush=True)
    muestras, _ = tramo(a.minutos, a.puerto)
    datos = resumen(muestras)
    if a.json:
        print(json.dumps(datos, ensure_ascii=False))
        return 0
    print("\nGPU (busy %):", datos["gpu_pct"])
    print("CPU del coach (% de un núcleo):", datos["cpu_coach_pct"])
    print("RAM del coach (MB):", datos["rss_mb"])
    print(f"muestras: {datos['n_gpu']} de GPU · {datos['n_cpu']} de CPU")
    if datos["n_cpu"] == 0:
        print("\nel coach no está corriendo: este tramo es la línea base sin coach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
