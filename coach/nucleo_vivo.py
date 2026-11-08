"""Piezas del modo en vivo: detectar partida, leer el HUD y ajustar el estado.

Eran los bloques anidados dentro de `bucle_vivo`; el bucle quedó en run.py.
"""
import threading
import time

from coach import servidor
from coach.nucleo_demo import juego_abierto


APERTURA = ["800", "1548066885", "1437614329"]   # ítems de apertura reales


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


def buscar_match(a, st):
    """match_id por las tres capas de `coach.fuentes.api_vivo` (HUD, cuenta, listado).

    Aquí vivía una copia del descubrimiento con menos reglas y sin caducidad, mientras
    la versión buena (`api_vivo.descubrir`, con TTL, caché y la regla de los 90 s sin
    señal) no la llamaba nadie: dos caminos, y el que corría era el tonto (QA de
    integración, 2026-11-08). Ahora hay uno solo.
    """
    if a.match:
        return a.match
    from coach.fuentes import api_vivo
    hallado = api_vivo.descubrir(cuenta=a.cuenta,
                                 con_hud=not getattr(a, "sin_hud", False))
    st["descubrimiento"] = hallado
    match = hallado.get("match")
    return int(match) if match else None


def hilo_hud(estado_hud, hud_cfg):
    """Lee reloj y oro del último cuadro de la captura compartida.

    Antes capturaba por su cuenta: 415 ms de `spectacle` por ciclo solo para el HUD.
    La captura compartida se enciende solo con el juego abierto: capturar el escritorio
    entero a 5.7 Hz cuesta ~10 % de un núcleo (medido el 2026-11-08) y sin juego no hay
    HUD que leer. Es el mismo chequeo que ya gateaba la lectura, así que no se pierde nada.
    """
    from coach.fuentes import captura, hud_rapido
    intervalo = 1.0 / max(0.5, float(hud_cfg.get("frecuencia_hz") or 2))
    while True:
        if not juego_abierto():
            captura.parar_global()
            time.sleep(5)
            continue
        try:
            d = hud_rapido.leer_actual(hud_cfg.get("max_edad_s", 2.0),
                                       hud_cfg.get("cajas") or None,
                                       hud_cfg.get("color_oro"))
        except Exception as exc:                        # noqa: BLE001
            print(f"HUD error: {type(exc).__name__}: {exc}", flush=True)
            d = None
        if d and d.get("t") is not None:
            estado_hud.update(d)
            # Sin esta marca `ajustar_con_hud` salía siempre por la primera línea
            # (`ts` quedaba en 0.0) y el reloj del HUD nunca llegaba al panel.
            estado_hud["ts"] = time.time()
        time.sleep(intervalo)


def arrancar_hud(a, hud_cfg, flags):
    """HUD por OCR en su propio hilo. Devuelve el dict que comparte con el bucle."""
    estado_hud = {"t": None, "oro": None, "ts": 0.0}
    if getattr(a, "sin_hud", False) or not (flags or {}).get("hud_ocr", True):
        return estado_hud
    threading.Thread(target=hilo_hud, args=(estado_hud, hud_cfg or {}),
                     daemon=True).start()
    return estado_hud


def publicar_apertura(conoc):
    """Build de apertura: los tres primeros ítems, sin inventar almas ni enemigos."""
    if not conoc:
        return False
    plan = []
    for iid in APERTURA:
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


def publicar_congelado(tick):
    """Aviso único: el stream se paró y el estado viejo no se republica."""
    servidor.EST.publicar({
        "listo": False,
        "fuente": "en_vivo",
        "mensaje": ("el broadcast dejó de mandar datos (último tick "
                    f"{tick}); reintentando"),
    })


def publicar_fuera_de_partida(est, cuenta):
    """Espectando una partida donde no está tu cuenta: el reloj sirve, el resto no."""
    servidor.EST.publicar({
        "listo": False,
        "mensaje": (f"la partida va {int(est.get('t', 0))//60}:"
                    f"{int(est.get('t', 0)) % 60:02d}, pero tu cuenta "
                    f"{cuenta} no está en ella"),
        "t": est.get("t"),
        "fuente": "en_vivo",
    })


def ajustar_con_hud(crudo, estado_hud, latencias, sin_hud):
    """Cambia reloj y oro del broadcast por los del HUD si la lectura es fresca.

    El broadcast llega 20-70 s tarde; el patrimonio se reconstruye con el gasto.
    """
    if (sin_hud or time.time() - estado_hud["ts"] >= 8
            or estado_hud.get("t") is None):
        return
    h_t = estado_hud["t"]
    api_t = crudo.get("t") or 0
    # El reloj del HUD se acepta solo si cuadra con el del broadcast
    # (el broadcast incluye el tiempo previo, por eso el margen amplio).
    if abs(h_t - api_t) <= 180:
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


def medir_latencias(a):
    """Latencias del panel, sin arrancar la captura solo para leer métricas.

    Con --sin-hud, `captura.global_()` encendía `spectacle` cada ciclo. Si la
    captura no está arriba (tests, sin pantalla, juego cerrado) los campos quedan en None.
    """
    metricas = {}
    if not getattr(a, "sin_hud", False):
        try:
            from coach.fuentes import captura
            metricas = captura.metricas_si_arriba()
        except Exception:                              # noqa: BLE001
            pass
    return {"captura_ms": metricas.get("ms_mediana"),
            "capturas": metricas.get("capturas"),
            "lectura_ms": None,
            "edad_hud_s": None,
            "broadcast_s": None}


def anotar_compras(est, conoc, items_previos, heroes_cta, compras):
    """Compras nuevas de los 12 jugadores (m_vecUpgrades); se guardan las últimas 3."""
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


def filtrar_por_oro(salida, crudo):
    """Deja en la salida solo lo que se paga con el oro sin gastar.

    El motor razona con patrimonio (almas totales), pero para "compra ahora"
    manda el oro sin gastar. Sin este filtro recomendaba ítems de 6,400
    teniendo 2,355 en el bolsillo.
    """
    oro = (crudo.get("yo") or {}).get("oro")
    if oro is None:
        return
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
