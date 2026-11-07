#!/usr/bin/env python3
"""Arranca el coach.  Uso:
    python3 run.py --fuente simulado     # demo sin juego
    python3 run.py --fuente ocr          # lectura de pantalla real
"""
import argparse, json, os, random, subprocess, sys, threading, time
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
               "oro": yo.get("oro"), "items": yo.get("items") or [],
               "bajas": yo.get("bajas") or 0, "muertes": yo.get("muertes") or 0,
               "asistencias": yo.get("asistencias") or 0},
        "aliados": limpio(est.get("aliados") or []),
        "enemigos": limpio(est.get("enemigos") or []),
        "confianza": 0.95,
        "fuente": "en_vivo",
        "notas": ["almas, héroes y KDA desde el broadcast de espectador "
                  "(latencia ~20-25 s del TV de Valve)"],
    }


_FLAGS = {}
_CFG = {}          # configuración cargada en main(), visible desde los bucles


def bucle_vivo(a, analizar):
    """Modo en vivo: deadlock-api + HUD por OCR para reloj y oro en tiempo real."""
    from coach import en_vivo, registro
    estado_hud = {"t": None, "oro": None, "ts": 0.0}

    hud_cfg = _CFG.get("hud") or {}
    if not getattr(a, "sin_hud", False) and _FLAGS.get("hud_ocr", True):
        def _hilo_hud():
            """Lee reloj y oro del último cuadro de la captura compartida.

            Antes capturaba por su cuenta en cada vuelta: 415 ms de `spectacle` por ciclo
            solo para el HUD. Ahora hay un único hilo capturando (coach/fuentes/captura.py)
            y este consume el último cuadro.
            """
            from coach.fuentes import hud_rapido
            intervalo = 1.0 / max(0.5, float(hud_cfg.get("frecuencia_hz") or 2))
            while True:
                if not juego_abierto():
                    time.sleep(5)
                    continue
                try:
                    d = hud_rapido.leer_actual(
                        hud_cfg.get("max_edad_s", 2.0),
                        hud_cfg.get("cajas") or None,
                        hud_cfg.get("color_oro"))
                except Exception as exc:                        # noqa: BLE001
                    print(f"HUD error: {type(exc).__name__}: {exc}", flush=True)
                    d = None
                if d and d.get("t") is not None:
                    estado_hud.update(d)
                time.sleep(intervalo)

        from coach.fuentes import captura
        captura.global_()
        threading.Thread(target=_hilo_hud, daemon=True).start()

    def _publicar_hud():
        """Desactivado: el OCR del HUD no es fiable como única fuente."""
        return False
        if getattr(a, "sin_hud", False):
            return False
        if estado_hud.get("t") is None or time.time() - estado_hud["ts"] > 8:
            return False
        h_t = estado_hud["t"]
        h_oro = estado_hud.get("oro")
        servidor.EST.publicar({
            "t": h_t,
            "almas": h_oro,
            "oro": h_oro,
            "estado": {"estado": "INICIO",
                       "motivo": "leyendo tu HUD en tiempo real",
                       "objetivo": "esperando enemigos del broadcast"},
            "economia": {"mias": h_oro, "media_enemiga": None, "delta_pct": None},
            "recomendaciones": [],
            "fuente": "hud",
            "notas": ["HUD OCR: reloj y oro de tu pantalla"],
        })
        return True

    escucha = None
    match_actual = None
    tick_previo = None
    tick_desde = time.time()
    avisado = False
    conoc = {}
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", "conocimiento.json"), encoding="utf-8") as f:
            conoc = json.load(f).get("items", {})
    except Exception:
        pass
    items_previos = {}
    heroes_cta = {}
    compras = []

    def _publicar_apertura():
        """Build de apertura mientras el broadcast todavía no existe.

        No inventa almas ni enemigos: solo los tres primeros ítems del plan.
        """
        if not conoc:
            return False
        plan = []
        for iid in ("800", "1548066885", "1437614329"):
            d = conoc.get(iid) or {}
            if d:
                plan.append({"id": iid, "nombre": d.get("nombre", iid),
                             "n": 0, "icono": f"/icono/{iid}"})
        servidor.EST.publicar({
            "t": 0, "almas": None, "oro": None,
            "estado": {"estado": "INICIO", "motivo": "partida iniciando",
                       "objetivo": "build de apertura"},
            "economia": {"mias": None, "media_enemiga": None, "delta_pct": None},
            "recomendaciones": [], "plan": plan, "fuente": "apertura",
            "notas": ["Build de apertura mientras llega el broadcast"],
        })
        return True
    while True:
        try:
            if a.match:
                match = a.match
            else:
                match = en_vivo.partida_activa(a.cuenta)
            if match is None:
                # El API no siempre lista la partida. El MATCH de la esquina
                # inferior derecha del HUD sí está cuando estás jugando.
                from coach import hud as hud_mod
                mid = hud_mod.leer_match_id()
                if mid:
                    match = mid
                    a.match = mid
                else:
                    if _publicar_hud():
                        time.sleep(2.0)
                        continue
                    if _publicar_apertura():
                        time.sleep(3.0)
                        continue
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
                tick_previo, tick_desde, avisado = None, time.time(), False
            est = escucha.estado
            if est is None or not est.get("jugadores"):
                if _publicar_hud():
                    time.sleep(2.0)
                    continue
                if _publicar_apertura():
                    time.sleep(3.0)
                    continue
                servidor.EST.publicar({"listo": False,
                                       "mensaje": f"conectando al broadcast "
                                                  f"({escucha.error or 'sin datos'})"})
                time.sleep(3.0)
                continue
            # Si el tick no cambia, el stream dejó de mandar datos. Mientras no avance
            # NO se publica el estado viejo: republicarlo actualizaría la marca de tiempo
            # y anularía el aviso de "datos congelados" (bug que encontró el revisor).
            if est.get("tick") != tick_previo:
                tick_previo, tick_desde, avisado = est.get("tick"), time.time(), False
            else:
                if _publicar_hud():
                    time.sleep(max(1.0, a.intervalo))
                    continue
                if time.time() - tick_desde > 12 and not avisado:
                    servidor.EST.publicar({
                        "listo": False,
                        "fuente": "en_vivo",
                        "mensaje": ("el broadcast dejó de mandar datos (último tick "
                                    f"{tick_previo}); reintentando"),
                    })
                    avisado = True
                time.sleep(max(1.0, a.intervalo))
                continue
            if not est.get("yo"):
                if _publicar_hud():
                    time.sleep(max(1.0, a.intervalo))
                    continue
                # Espectando una partida donde no está tu cuenta: el reloj sirve, pero
                # no hay "yo" ni equipos. Mejor decirlo que mostrar un panel vacío.
                servidor.EST.publicar({
                    "listo": False,
                    "mensaje": (f"la partida va {int(est.get('t', 0))//60}:"
                                f"{int(est.get('t', 0)) % 60:02d}, pero tu cuenta "
                                f"{a.cuenta} no está en ella"),
                    "t": est.get("t"),
                    "fuente": "en_vivo",
                })
                time.sleep(max(1.0, a.intervalo))
                continue
            crudo = estado_desde_vivo(est, a.cuenta)
            # Métricas de captura: si la captura compartida no está arriba (tests, o
            # sesión sin pantalla) esto queda en None y no rompe nada.
            try:
                from coach.fuentes import captura as _cap
                metricas_captura = _cap.global_().metricas()
            except Exception:                                  # noqa: BLE001
                metricas_captura = {}
            latencias = {
                "captura_ms": metricas_captura.get("ms_mediana"),
                "capturas": metricas_captura.get("capturas"),
                "lectura_ms": None,
                "edad_hud_s": None,
                "broadcast_s": None,
            }
            # El broadcast llega 20-70 s tarde (y más si hubo pausa). El HUD por
            # OCR da el reloj y el oro reales; el patrimonio se reconstruye con
            # el gasto que ya trae el broadcast.
            if (not getattr(a, "sin_hud", False)
                    and time.time() - estado_hud["ts"] < 8
                    and estado_hud.get("t") is not None):
                h_t = estado_hud["t"]
                api_t = crudo.get("t") or 0
                # El reloj del HUD se acepta solo si cuadra con el del broadcast
                # (el broadcast incluye el tiempo previo, por eso el margen amplio).
                if h_t is not None and abs(h_t - api_t) <= 180:
                    crudo["t"] = h_t
                    # Diferencia real entre lo que ve el jugador y lo que manda el TV de
                    # Valve: es la latencia del broadcast, medida, no estimada.
                    latencias["broadcast_s"] = round(h_t - api_t, 1)
                    latencias["edad_hud_s"] = round(time.time() - estado_hud["ts"], 2)
                    latencias["lectura_ms"] = round(
                        sum(x for x in (estado_hud.get("ms_reloj"),
                                        estado_hud.get("ms_oro")) if x) or 0, 1)
                    nota = f"HUD OCR: reloj {h_t//60}:{h_t%60:02d}"
                else:
                    nota = "reloj del broadcast"
                h_oro = estado_hud.get("oro")
                api_oro = crudo["yo"].get("oro") or 0
                if (h_oro is not None and api_oro
                        and abs(h_oro - api_oro) <= max(400, api_oro * 0.5)):
                    crudo["yo"]["oro"] = h_oro
                    crudo["yo"]["almas"] = max(
                        0, (crudo["yo"].get("almas") or 0) - api_oro + h_oro)
                    nota += f" · {h_oro:,} sin gastar"
                crudo["notas"] = [nota]
            # Compras nuevas de cualquier jugador (el broadcast manda m_vecUpgrades
            # de los 12). Se muestran como avisos recientes en el panel.
            for j in est.get("jugadores") or []:
                cta = j.get("cuenta")
                if j.get("heroe"):
                    heroes_cta[cta] = j["heroe"]
                act = set(j.get("items") or [])
                ant = items_previos.get(cta)
                if ant is not None:
                    for iid in act - ant:
                        nom = (conoc.get(str(iid)) or {}).get("nombre", str(iid))
                        quien = j.get("heroe") or heroes_cta.get(cta) or "Jugador"
                        compras.append({"texto": f"{quien}: {nom}",
                                        "item": str(iid), "ts": time.time()})
                items_previos[cta] = act
            del compras[:-3]
            salida = analizar(crudo)
            salida["latencia"] = latencias
            salida["compras"] = list(compras)
            registro.anotar(salida, crudo)
            # El motor razona con patrimonio (almas totales), pero para "compra ahora"
            # manda el oro sin gastar. Sin este filtro recomendaba ítems de 6,400
            # teniendo 2,355 en el bolsillo.
            oro = (crudo.get("yo") or {}).get("oro")
            if oro is not None:
                recs = salida.get("recomendaciones") or []
                pagables = [r for r in recs if (r.get("costo") or 0) <= oro]
                if pagables:
                    for r in pagables:
                        r["alcanza"] = True
                    salida["recomendaciones"] = pagables[:3]
                elif recs:
                    # Mantener el objetivo visible aunque no alcance: el panel muestra
                    # el icono grande y cuánto falta, en vez de "sin compra".
                    objetivo = recs[0]
                    objetivo["alcanza"] = False
                    objetivo["faltan"] = max(0, (objetivo.get("costo") or 0) - oro)
                    salida["recomendaciones"] = [objetivo]
                    salida["notas"] = [f"{oro:,} almas sin gastar: faltan "
                                       f"{objetivo['faltan']:,} para "
                                       f"{objetivo.get('nombre')}"]
                salida["oro"] = oro
            # Las 12 almas del marcador, en el mismo campo que usa el modo OCR, para
            # que los dos paneles muestren lo mismo sin importar la fuente.
            doce = ([crudo["yo"].get("almas")]
                    + [j.get("almas") for j in crudo["aliados"]]
                    + [j.get("almas") for j in crudo["enemigos"]])
            # El broadcast puede traer menos de 12 filas: se fija la longitud para que
            # quien lo consuma pueda indexar 0..11 sin sorpresas.
            salida["almas_12"] = (doce + [None] * 12)[:12]
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
    ap.add_argument("--fuente", default="simulado", choices=["simulado", "ocr", "vivo", "auto"])
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
    ap.add_argument("--sin-hud", action="store_true",
                    help="no leer reloj/almas del HUD por OCR (usa solo el broadcast)")
    ap.add_argument("--mi-heroe", default=None,
                    help="héroe propio para identificar tu columna en el marcador")
    ap.add_argument("--mi-columna", type=int, default=None, choices=range(6),
                    help="columna aliada (0-5) que eres tú, si el héroe no se detecta")
    ap.add_argument("--imagen", default=None,
                    help="en modo ocr, leer esta captura en vez de la pantalla "
                         "(para probar sin el juego abierto)")
    a = ap.parse_args()

    if a.fuente in ("ocr", "vivo", "auto"):
        aviso_vram()

    # El aviso de "datos congelados" tiene que ser más lento que la cadencia real de
    # publicación, o con --intervalo alto el panel parpadearía sin nada roto.
    servidor.UMBRAL_RANCIO_S = max(8.0, 3.0 * max(0.2, a.intervalo))

    # Configuración con defaults y validación (config/coach.yaml). Si el archivo falta o
    # está roto, `cargar()` devuelve los valores por defecto y anota el aviso: el coach
    # nunca deja de arrancar por un YAML.
    from coach.config import cargar as cargar_config
    cfg = cargar_config()
    _FLAGS.update(cfg.flags)
    _CFG.update({"fuentes": cfg.fuentes, "hud": (cfg.fuentes or {}).get("hud") or {}})
    cfg_motor = dict(cfg.motor)
    if not cfg.flags.get("patrones_nuevos", True):
        # Rollback de los patrones nuevos sin tocar código.
        cfg_motor.update({"w_presupuesto": 0.0, "w_recuperacion": 0.0,
                          "w_balance": 0.0, "contexto_activo": False})
    if cfg.avisos:
        print("  avisos de config: " + "; ".join(cfg.avisos[:3]))

    print("cargando conocimiento…")
    m = Motor(cfg=cfg_motor)
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
        salida = con_historial(est.procesar(e, m.analizar_dict(d)))
        # El marcador de 12 almas se arma en un solo sitio: así el demo y las
        # inyecciones de prueba muestran lo mismo que el modo vivo.
        if not salida.get("almas_12"):
            doce = ([e.yo.almas] + [j.almas for j in e.aliados]
                    + [j.almas for j in e.enemigos])
            salida["almas_12"] = (doce + [None] * 12)[:12]
        return salida

    servidor.arrancar(a.puerto, analizador=analizar)

    print(f"panel: http://127.0.0.1:{a.puerto}")

    if a.fuente == "simulado":
        t = float(a.t_inicial)
        while True:
            # si alguien inyecta un estado a mano, el demo se calla un rato
            if time.time() - servidor.EST.manual_ts > 120:
                crudo = estado_simulado(min(t, 2399))
                salida = analizar(crudo)
                # El demo rellena el mismo campo de 12 almas que llenan el modo vivo y el
                # OCR: así la sección EQUIPO del panel se puede probar sin partida.
                doce = ([crudo["yo"].get("almas")]
                        + [j.get("almas") for j in crudo["aliados"]]
                        + [j.get("almas") for j in crudo["enemigos"]])
                salida["almas_12"] = (doce + [None] * 12)[:12]
                servidor.EST.publicar(salida)
            if a.acelerar > 0:
                t += 20 * a.acelerar
                if t > 2400:
                    t = 0
            time.sleep(max(0.2, a.intervalo))
    elif a.fuente == "vivo":
        bucle_vivo(a, analizar)
    elif a.fuente == "auto":
        # Decide al arrancar: si tu cuenta está en una partida, el broadcast da todo
        # (almas por jugador, héroes, KDA) sin depender del marcador; si no, se lee la
        # pantalla como siempre.
        from coach import en_vivo
        match = a.match or en_vivo.partida_activa(a.cuenta)
        if match:
            print(f"automático: partida en vivo {match} -> broadcast")
            a.match = match
            bucle_vivo(a, analizar)
        else:
            print("automático: sin partida en vivo -> lectura por pantalla")
            bucle_ocr(a, analizar)
    else:
        bucle_ocr(a, analizar)


if __name__ == "__main__":
    main()
