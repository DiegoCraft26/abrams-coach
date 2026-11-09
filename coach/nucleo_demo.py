"""Entorno y partida simulada: lo que permite arrancar sin el juego abierto.

Son los bloques que estaban sueltos al principio de run.py. Sin dependencias de
la app: solo `systemctl`/`ps` para mirar el entorno y el catálogo para el demo.
"""
import glob
import json
import os
import subprocess

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ruta_datos(nombre):
    return os.path.join(_RAIZ, "data", nombre)


def leer_conocimiento():
    """Ítems del catálogo; {} si el archivo falta o está roto."""
    try:
        with open(ruta_datos("conocimiento.json"), encoding="utf-8") as f:
            return json.load(f).get("items") or {}
    except Exception:
        return {}


def aviso_vram():
    """Si el modelo local está cargado, avisa: compite por la GPU con el juego."""
    try:
        estado = subprocess.run(["systemctl", "--user", "is-active", "llama-server.service"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        if estado != "active":
            return
        vram = 0
        for ruta in glob.glob("/sys/class/drm/card*/device/mem_info_vram_used"):
            try:
                vram = max(vram, int(open(ruta).read()) / 1048576)
            except Exception:
                pass
        print(f"AVISO: llama-server está activo y usa {vram:.0f} MB de VRAM.")
        print("       Eso le quita memoria a Deadlock. Páralo con:")
        print("       ./modo_juego.sh on   (o systemctl --user stop llama-server)")
    except Exception:
        pass


def juego_abierto():
    """¿Está corriendo Deadlock? Si no, no tiene sentido capturar pantalla.

    `comm` del proceso es steam.exe/wine, no deadlock; hay que mirar los args.
    """
    try:
        salida = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                                text=True, timeout=5).stdout.lower()
        return any(n in salida for n in ("deadlock.exe", "deadlock/game/bin",
                                         "project8"))
    except Exception:
        return True


def inventario_simulado(t):
    """Inventario plausible de Abrams según el minuto."""
    conoc = leer_conocimiento()
    disponibles = [i for i, d in conoc.items() if (d["costo"] or 0) <= 1600]
    disponibles.sort(key=lambda i: -conoc[i]["lift_residual"])
    if t < 600:
        return disponibles[:2]
    if t < 1200:
        return disponibles[:4]
    return disponibles[:6]


def estado_simulado(t):
    """Partida plausible para probar el motor y la UI.

    Los héroes son reales a propósito: con nombres inventados ("a2", "e0") el panel web
    pedía /icono-heroe/a2 y dejaba una imagen rota, que hacía fallar la puerta de
    calidad de la UI. Detectado el 2026-11-07.
    """
    progreso = t / 2400
    almas = int(300 + progreso * 12000)
    enemigos = [{"heroe": h, "almas": int(almas * (0.85 + 0.05 * i))}
                for i, h in enumerate(["haze", "lash", "seven", "bebop", "wraith"])]
    return {
        "t": t,
        # Oro sin gastar plausible: sin esto el demo no puede pagar nada y el panel
        # se queda siempre en AHORRAR, que no enseña el estado normal.
        "yo": {"heroe": "Abrams", "almas": almas, "oro": int(almas * 0.40),
               "items": inventario_simulado(t)},
        "aliados": [{"heroe": "kelvin", "almas": int(almas * 0.9)},
                    {"heroe": "dynamo", "almas": int(almas * 0.8)}],
        "enemigos": enemigos,
        "confianza": 0.9,
        "fuente": "simulado",
    }
