#!/usr/bin/env python3
"""Arranca el coach.  Uso:
    python3 run.py --fuente simulado     # demo sin juego
    python3 run.py --fuente ocr          # lectura de pantalla real
"""
import argparse, json, os, random, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coach import servidor
from coach.motor_api import Motor
from coach.estado import Estado, Jugador
from coach.estabilizador import Estabilizador


APERTURA = ["800", "1548066885", "1437614329"]   # ítems de apertura reales
MEDIO = ["2971868509", "3077079169", "1342610602"]


def inventario_simulado(t):
    """Inventario plausible de Abrams según el minuto."""
    import json, os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "conocimiento.json")
    conoc = json.load(open(ruta))["items"]
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
        "yo": {"heroe": "Abrams", "almas": almas, "items": inventario_simulado(t)},
        "aliados": [{"heroe": "kelvin", "almas": int(almas * 0.9)},
                    {"heroe": "dynamo", "almas": int(almas * 0.8)}],
        "enemigos": enemigos,
        "confianza": 0.9,
        "fuente": "simulado",
    }


def aviso_vram():
    """Si el modelo local está cargado, avisa: compite por la GPU con el juego."""
    try:
        estado = subprocess.run(["systemctl", "--user", "is-active", "llama-server.service"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        if estado == "active":
            vram = 0
            import glob
            for ruta in glob.glob("/sys/class/drm/card*/device/mem_info_vram_used"):
                try:
                    vram = max(vram, int(open(ruta).read())/1048576)
                except Exception:
                    pass
            print(f"AVISO: llama-server está activo y usa {vram:.0f} MB de VRAM.")
            print("       Eso le quita memoria a Deadlock. Páralo con:")
            print("       ./modo_juego.sh on   (o systemctl --user stop llama-server)")
    except Exception:
        pass


def juego_abierto():
    """¿Está corriendo Deadlock? Si no, no tiene sentido capturar pantalla."""
    try:
        salida = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True, timeout=5).stdout.lower()
        return any(n in salida for n in ("deadlock", "project8"))
    except Exception:
        return True


def estado_desde_vivo(est, cuenta=None):
    """Traduce el estado del cliente en vivo al formato que come el motor."""
    yo = est.get("yo") or {}
    cuenta_txt = str(int(cuenta)) if cuenta else None

    def limpio(lista):
        return [{"heroe": j.get("heroe"), "almas": j.get("almas"),
                 "bajas": j.get("bajas") or 0, "muertes": j.get("muertes") or 0,
                 "asistencias": j.get("asistencias") or 0}
                for j in lista if str(j.get("cuenta")) != cuenta_txt]

    return {
        "t": est.get("t") or 0,
        "yo": {"heroe": yo.get("heroe"), "almas": yo.get("almas"),
               "bajas": yo.get("bajas") or 0, "muertes": yo.get("muertes") or 0,
               "asistencias": yo.get("asistencias") or 0},
        "aliados": limpio(est.get("aliados") or []),
        "enemigos": limpio(est.get("enemigos") or []),
        "confianza": 0.95,
        "fuente": "en_vivo",
        "notas": ["almas, héroes y KDA desde el broadcast de espectador "
                  "(latencia ~20-25 s del TV de Valve)"],
    }


def bucle_vivo(a, analizar):
    """Modo en vivo: deadlock-api. Sin OCR, sin VRAM, ~KB de RAM."""
    from coach import en_vivo
    escucha = None
    match_actual = None
    while True:
        try:
            if a.match:
                match = a.match
            else:
                match = en_vivo.partida_activa(a.cuenta)
            if match is None:
                servidor.EST.publicar({"listo": False,
                                       "mensaje": f"la cuenta {a.cuenta} no está en partida"})
                time.sleep(10.0)
                continue
            if match != match_actual:
                if escucha:
                    escucha.parar()
                print(f"partida en vivo: {match}")
                escucha = en_vivo.Escucha(match, cuenta=a.cuenta).arrancar()
                match_actual = match
            est = escucha.estado
            if est is None or not est.get("jugadores"):
                servidor.EST.publicar({"listo": False,
                                       "mensaje": f"conectando al broadcast "
                                                  f"({escucha.error or 'sin datos'})"})
                time.sleep(3.0)
                continue
            salida = analizar(estado_desde_vivo(est, a.cuenta))
            servidor.EST.publicar(salida)
        except Exception as exc:                                    # noqa: BLE001
            servidor.EST.publicar({"listo": False, "mensaje": f"error en vivo: {exc}"})
        time.sleep(max(1.0, a.intervalo))


def bucle_ocr(a, analizar):
    """Modo OCR: captura de pantalla + plantillas del propio juego."""
    from coach import lector, marcador, registro
    mi_heroe = (a.mi_heroe or "").strip().lower() or None
    while True:
        if not a.imagen and not juego_abierto():
            servidor.EST.publicar({"listo": False,
                                   "mensaje": "Deadlock no está abierto: en espera"})
            time.sleep(5.0)
            continue
        try:
            img = a.imagen or lector.capturar(fuente=a.captura)
            lec = marcador.leer_captura(img, mi_heroe=mi_heroe)
            almas_12 = lec["almas"]["aliados"] + lec["almas"]["enemigos"]

            propias = lec.get("almas_propias")
            if propias is None and a.mi_columna is not None:
                propias = lec["almas"]["aliados"][a.mi_columna]

            if propias is None:
                servidor.EST.publicar({
                    "listo": False,
                    "mensaje": ("veo el marcador y las 12 almas, pero no sé cuál eres tú. "
                                "Pasá --mi-heroe abrams o --mi-columna N "
                                "(o corré en modo vivo)."),
                    "almas_12": almas_12,
                    "tiempo_s": lec["tiempo_s"],
                    "almas_aliados": lec["almas"]["aliados"],
                    "almas_enemigos": lec["almas"]["enemigos"],
                })
                time.sleep(max(0.2, a.intervalo))
                continue

            notas = []
            if lec["tiempo_s"] is None:
                notas.append("no leí el reloj")
            if not lec["ok"]:
                notas.append(lec["motivo"])
            notas.append("no leo tus ítems ni la composición por OCR "
                         "(pendiente: requiere captura de partida normal)")

            estado = {
                "t": lec["tiempo_s"] or 0,
                "yo": {"heroe": a.mi_heroe or "Abrams", "almas": propias, "items": []},
                "aliados": [{"almas": x} for i, x in enumerate(lec["almas"]["aliados"])
                            if i != (a.mi_columna if a.mi_columna is not None else -1)],
                "enemigos": [{"almas": x} for x in lec["almas"]["enemigos"]],
                "confianza": round(float(lec["confianza"]), 2),
                "fuente": "ocr",
                "notas": notas,
            }
            salida = analizar(estado)
            salida["almas_12"] = almas_12
            servidor.EST.publicar(salida)
            if salida.get("recomendaciones"):
                registro.anotar(salida, estado)
        except Exception as exc:                                    # noqa: BLE001
            servidor.EST.publicar({"listo": False, "mensaje": f"error de lectura: {exc}"})
        time.sleep(max(0.2, a.intervalo))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuente", default="simulado", choices=["simulado", "ocr", "vivo"])
    ap.add_argument("--puerto", type=int, default=8090)
    ap.add_argument("--captura", default="auto", choices=["auto", "bufer", "spectacle"],
                    help="fuente de imagen: reutilizar el bufer de pantalla o capturar aparte")
    ap.add_argument("--intervalo", type=float, default=1.0,
                    help="segundos entre lecturas en modo ocr/vivo")
    ap.add_argument("--acelerar", type=float, default=30.0,
                    help="factor de tiempo en modo simulado; 0 congela el estado "
                         "(necesario para que la puerta de calidad de la UI mida "
                         "los 3 tamaños sobre el mismo estado)")
    ap.add_argument("--t-inicial", type=float, default=900.0,
                    help="segundo de partida en el que arranca/congela el demo")
    ap.add_argument("--cuenta", type=int, default=TU_STEAMID64,
                    help="SteamID64 de Diego, para el modo vivo")
    ap.add_argument("--match", type=int, default=None,
                    help="match_id directo (en vez de buscarlo por cuenta)")
    ap.add_argument("--mi-heroe", default=None,
                    help="héroe propio para identificar tu columna en el marcador")
    ap.add_argument("--mi-columna", type=int, default=None, choices=range(6),
                    help="columna aliada (0-5) que eres tú, si el héroe no se detecta")
    ap.add_argument("--imagen", default=None,
                    help="en modo ocr, leer esta captura en vez de la pantalla "
                         "(para probar sin el juego abierto)")
    a = ap.parse_args()

    if a.fuente in ("ocr", "vivo"):
        aviso_vram()

    print("cargando conocimiento…")
    m = Motor()
    print(f"  {len(m.conoc['items'])} ítems · {len(m.conoc['pares'])} pares · "
          f"{len(m.conoc['counters'])} matchups")

    est = Estabilizador()
    historial = __import__("collections").deque(maxlen=240)

    def con_historial(salida):
        if salida.get("almas") is not None:
            historial.append({"t": salida.get("t", 0), "a": salida["almas"],
                              "e": (salida.get("economia") or {}).get("media_enemiga")})
        salida["historial"] = list(historial)[-80:]
        return salida

    def analizar(d):
        e = m.estado_desde(d)
        return con_historial(est.procesar(e, m.analizar_dict(d)))

    servidor.arrancar(a.puerto, analizador=analizar)
    print(f"panel: http://127.0.0.1:{a.puerto}")

    if a.fuente == "simulado":
        t = float(a.t_inicial)
        while True:
            # si alguien inyecta un estado a mano, el demo se calla un rato
            if time.time() - servidor.EST.manual_ts > 120:
                servidor.EST.publicar(analizar(estado_simulado(min(t, 2399))))
            if a.acelerar > 0:
                t += 20 * a.acelerar
                if t > 2400:
                    t = 0
            time.sleep(max(0.2, a.intervalo))
    elif a.fuente == "vivo":
        bucle_vivo(a, analizar)
    else:
        bucle_ocr(a, analizar)


if __name__ == "__main__":
    main()
