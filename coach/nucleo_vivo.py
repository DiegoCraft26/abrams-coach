"""Piezas del modo en vivo: detectar partida, leer el HUD y ajustar el estado.

Eran los bloques anidados dentro de `bucle_vivo`; el bucle quedó en run.py.
"""
import threading
import time

from coach import servidor
from coach.nucleo_demo import juego_abierto


# Apertura real de Abrams: los tres ítems de 800 que más se compran (1.9 M de partidas).
# Aquí había un "800" en lugar de un id: es un costo, no un ítem, así que el panel
# enseñaba dos compras donde van tres (visto el 2026-11-09 en la ranked).
# La apertura ya no vive aquí: `coach/apertura.py` resuelve por héroe (banco de 626
# partidas para Abrams, pozo del API para el resto). Se dejó de escribir a mano porque
# contradecía al banco.

# Estado del filtro de almas del modo pantalla (ver `_oro_estable`).
_PANTALLA = {"oro": None, "cand": None, "veces": 0}

# El contador de almas del HUD todavía no se puede leer con seguridad: tesseract
# confunde dígitos con el font del juego (leyó 89 y 221 donde decía 4489) y el banco de
# plantillas no tiene el glifo '6'. Hasta que las plantillas lean 4 de 4, el modo
# pantalla publica el reloj y calla las almas: antes nada que un número falso.
ORO_PANTALLA_FIABLE = False

# Último reloj bueno del modo pantalla (ver `_reloj_estable`).
_RELOJ = {"t": None, "cand": None, "veces": 0}

# Desfase medido entre el reloj del HUD y el del broadcast (ver `ajustar_con_hud`).
_RELOJ_HUD = {"desfase": None, "ts": 0.0}


def olvidar_reloj_hud():
    """Se llama al cambiar de partida: el desfase de la anterior no vale."""
    _RELOJ_HUD["desfase"] = None
    _RELOJ_HUD["ts"] = 0.0


def estado_desde_vivo(est, cuenta=None):
    """Traduce el estado del cliente en vivo al formato que come el motor."""
    yo = est.get("yo") or {}
    # La cuenta puede faltar (match montado por el id del HUD). Si el "yo" se
    # identificó por héroe, se usa su cuenta para no repetirlo en aliados.
    if cuenta:
        cuenta_txt = str(int(cuenta))
    elif yo.get("cuenta") is not None:
        cuenta_txt = str(yo["cuenta"])
    else:
        cuenta_txt = None

    def limpio(lista):
        return [{"heroe": j.get("heroe"), "almas": j.get("almas"),
                 "bajas": j.get("bajas") or 0, "muertes": j.get("muertes") or 0,
                 "asistencias": j.get("asistencias") or 0,
                 # Ítems visibles en el broadcast: base para counterear lo que compran.
                 "items": [str(x) for x in (j.get("items") or [])]}
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
        "notas": ["almas, héroes, ítems y KDA leídos del broadcast por HTTP "
                  "(consulta de ~1.3 s; el retardo del TV de Valve no se mide aquí)"],
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
    """Lee reloj y oro del HUD **bajo demanda**, y calla cuando el broadcast ya informa.

    Antes había un hilo capturando el escritorio entero a 2 Hz aunque no hubiera partida;
    después, un cuadro completo cada 2 s (64 ms de readback medidos).

    Medido el 2026-11-15 con el juego abierto: cada petición de captura cuesta ~29 ms
    porque KWin espera al siguiente cuadro del compositor (con el juego cerrado eran
    0.9 ms). Por eso, cuando el broadcast trae el reloj —partida en vivo—, este hilo **no
    captura nada**: el dato ya viene por HTTP y el readback solo sirve para molestar.
    """
    from .fuentes import hud_rapido
    hz = float(hud_cfg.get("frecuencia_hz") or 0.5)
    # Piso configurable: `--intervalo` (o ABRAMS_INTERVALO) puede espaciar el OCR a 4 s
    # cuando el equipo va justo de CPU. Sin broadcast, el reloj se retrasa lo mismo.
    intervalo = max(float(hud_cfg.get("intervalo_min_s") or 2.0),
                    1.0 / max(0.1, hz))
    cajas = hud_cfg.get("cajas") or None
    color = hud_cfg.get("color_oro")
    while True:
        if not juego_abierto():
            time.sleep(5)
            continue
        # Con broadcast fresco el reloj ya está resuelto: ni una captura. Diez segundos
        # de margen para que un corte del stream no deje el panel sin reloj.
        if time.time() - float(estado_hud.get("broadcast_ts") or 0) < 10:
            estado_hud["hud_pausado"] = True
            time.sleep(intervalo)
            continue
        estado_hud["hud_pausado"] = False
        # Una sola captura del monitor por ciclo (33 ms medidos con el juego abierto) en
        # vez de una por caja (3 × 29 ms = 87 ms): ver MarcoPerezoso.
        cuadro = hud_rapido.MarcoPerezoso(tamano=_tamano_escritorio())
        if cuadro is not None:
            try:
                d = hud_rapido.leer(cuadro, cajas, color)
            except Exception as exc:                        # noqa: BLE001
                print(f"HUD error: {type(exc).__name__}: {exc}", flush=True)
                d = None
            if d and d.get("t") is not None:
                estado_hud.update(d)
                estado_hud["ts"] = time.time()
        time.sleep(intervalo)


_TAMANO = {"ts": 0.0, "v": (4480, 1440)}


def _tamano_escritorio(vida_s=300.0):
    """Tamaño total del escritorio (todos los monitores). Cacheado hasta 5 min.

    Las cajas del HUD están en coordenadas absolutas del escritorio y se escalan por
    este tamaño: si cambia la resolución, se recalculan solas.
    """
    ahora = time.time()
    if ahora - _TAMANO["ts"] < vida_s:
        return _TAMANO["v"]
    try:
        from .fuentes import captura_bajo_demanda as cbd
        lista = cbd.salidas()
        if lista:
            ancho = max(s[1] + s[3] for s in lista)
            alto = max(s[2] + s[4] for s in lista)
            _TAMANO.update({"ts": ahora, "v": (ancho, alto)})
    except Exception:                                         # noqa: BLE001
        pass
    return _TAMANO["v"]


def arrancar_hud(a, hud_cfg, flags):
    """HUD por OCR en su propio hilo. Devuelve el dict que comparte con el bucle."""
    estado_hud = {"t": None, "oro": None, "ts": 0.0}
    if getattr(a, "sin_hud", False) or not (flags or {}).get("hud_ocr", True):
        return estado_hud
    # Aquí arrancaba `captura.global_()` con intervalo 0.4 s: un hilo que capturaba los
    # DOS monitores (4480×1440) 2,3 veces por segundo y **no lo leía nadie** (el HUD usa
    # `MarcoPerezoso`, una captura por ciclo, y `leer_actual` no tiene llamadas). Medido
    # el 2026-11-18 en reposo: 39 ms por captura → ~92 ms de CPU/s (9 % de un núcleo) más
    # 2,3 readbacks del compositor por segundo. Era el coste más caro del coach y no
    # servía para nada.
    #
    # `--intervalo` manda en la cadencia del HUD: antes el OCR tenía un piso duro de 2 s
    # y la opción no cambiaba nada (el comentario de partida.sh decía lo contrario).
    hud_cfg = {**(hud_cfg or {}),
               "intervalo_min_s": max(2.0, float(getattr(a, "intervalo", 1.0) or 1.0))}
    threading.Thread(target=hilo_hud, args=(estado_hud, hud_cfg),
                     daemon=True).start()
    return estado_hud


def _oro_estable(oro):
    """Solo publica un número de almas que se repita tres veces y que sea creíble.

    El OCR del contador del HUD todavía confunde dígitos (leyó 89 y 221 donde decía
    4489, y una vez 23 751 con la ranked del 2026-11-09), y la confianza de tesseract
    no sirve para filtrarlo: sale 0-18 en todas. Mientras el banco de plantillas no
    tenga los dígitos que le faltan, se exige que el mismo número salga tres lecturas
    seguidas y que no pegue un salto imposible respecto al anterior. Si no, el panel
    no enseña almas: antes nada que un dato falso.
    """
    if oro is None:
        return _PANTALLA["oro"]
    if oro == _PANTALLA["oro"]:
        _PANTALLA["cand"], _PANTALLA["veces"] = None, 0
        return _PANTALLA["oro"]
    previo = _PANTALLA["oro"]
    if previo is not None and abs(oro - previo) > 2500:
        _PANTALLA["cand"], _PANTALLA["veces"] = None, 0
        return previo
    if oro == _PANTALLA["cand"]:
        _PANTALLA["veces"] += 1
    else:
        _PANTALLA["cand"], _PANTALLA["veces"] = oro, 1
    if _PANTALLA["veces"] >= 3:
        _PANTALLA["oro"], _PANTALLA["cand"], _PANTALLA["veces"] = oro, None, 0
    return _PANTALLA["oro"]


def _reloj_estable(t):
    """Descarta lecturas de reloj imposibles sin quedarse clavado.

    El OCR del reloj acierta casi siempre (44 de 45 lecturas seguidas de un segundo a
    otro), pero de vez en cuando devuelve una barbaridad: en la ranked del 2026-11-09
    saltó de 2:14 a 79:22. El reloj solo puede avanzar; un salto de más de 30 s o un
    retroceso se ignoran. Si el valor raro se repite tres veces se acepta, porque
    también es lo que pasa al empezar una partida nueva (el reloj vuelve a cero).
    """
    previo = _RELOJ["t"]
    if previo is None:
        _RELOJ["t"] = t
        return t
    if 0 <= t - previo <= 30:
        _RELOJ["t"], _RELOJ["cand"], _RELOJ["veces"] = t, None, 0
        return t
    if t == _RELOJ["cand"]:
        _RELOJ["veces"] += 1
    else:
        _RELOJ["cand"], _RELOJ["veces"] = t, 1
    if _RELOJ["veces"] >= 3:
        _RELOJ["t"], _RELOJ["cand"], _RELOJ["veces"] = t, None, 0
    return _RELOJ["t"]


def plan_inicial(conoc, cuantos=5, heroe=None):
    """Las compras del arranque, con su costo, para cuando no hay broadcast.

    Primero la apertura fija (los tres 800 que más se compran) y después las siguientes
    por volumen real de compras, todas de 800. No se usa `min_compra` para ordenar: ese
    campo es la mediana de todo el juego, no el minuto de la primera compra, y ponía
    «min 16» en ítems que se compran al minuto 2.
    """
    if not conoc:
        return []
    items = conoc.get("items") if isinstance(conoc.get("items"), dict) else conoc
    items = {str(k): v for k, v in (items or {}).items() if isinstance(v, dict)}

    from . import apertura
    # La apertura sale del banco (Abrams) o del pozo del API (otros héroes). Antes era
    # una constante escrita a mano que contradecía al banco: el panel decía Melee
    # Lifesteal y las 626 partidas dicen Spirit Strike.
    orden = [iid for iid in apertura.ids(heroe, cuantos) if iid in items]
    resto = [(d.get("n", 0), iid) for iid, d in items.items()
             if iid not in orden and d.get("tier") == 1 and (d.get("costo") or 9999) <= 800]
    resto.sort(reverse=True)
    orden += [iid for _, iid in resto[:max(0, cuantos - len(orden))]]

    plan = []
    for iid in orden:
        d = items[iid]
        costo = d.get("costo")
        plan.append({"id": iid, "nombre": d.get("nombre", iid),
                     "costo": int(costo) if costo else None, "n": 0,
                     "icono": f"/icono/{iid}"})
    return plan


def _notas_pantalla(oro):
    """Lo que el panel dice del modo pantalla, sin adornar lo que no se sabe."""
    notas = ["reloj leído de tu pantalla; sin broadcast no hay enemigos, equipo ni "
             "historial"]
    if oro is None:
        notas.append("las almas todavía no se leen con seguridad: no se muestran")
    return notas


def publicar_pantalla(estado_hud, analizar, latencias=None, conoc=None,
                      max_edad_s=3.0, inventario=None, vision=None, nota=None):
    """Modo pantalla: sin broadcast, se lee el reloj y las almas del propio HUD.

    Es el camino que sirve en ranked, práctica y bots, donde Valve no retransmite
    nada. Da lo que de verdad está en la pantalla: reloj y almas. No inventa
    enemigos, equipo ni ítems, y lo dice en las notas.
    """
    t = estado_hud.get("t")
    ts = estado_hud.get("ts") or 0.0
    if t is None or (time.time() - ts) > max_edad_s:
        return False
    t = _reloj_estable(int(t))
    oro = _oro_estable(estado_hud.get("oro")) if ORO_PANTALLA_FIABLE else None
    # Inventario de la tienda leído por visión: llega con su edad y su fuente. Si no hay,
    # se sigue jugando sin inventario y se dice; nunca se rellena con lo que no se vio.
    items = list((inventario or {}).get("inventario") or [])
    crudo = {
        "t": int(t),
        "yo": {"almas": oro, "items": [i.get("id") for i in items],
               "bajas": 0, "muertes": 0, "asistencias": 0},
        "aliados": [], "enemigos": [],
        "confianza": 0.6,
        "fuente": "pantalla",
        "notas": _notas_pantalla(oro),
    }
    # Fase real del juego según el console.log: sirve para decir «en partida» sin
    # adivinar cuando no hay broadcast ni HUD legible.
    try:
        from .fuentes import log_juego
        fase_juego = log_juego.fase()
        if fase_juego:
            salida_fase = {"fase_juego": fase_juego,
                           "heroe_juego": log_juego.heroe()}
        else:
            salida_fase = {}
    except Exception:                                     # noqa: BLE001
        salida_fase = {}
    salida = analizar(crudo)
    salida.update(salida_fase)
    if not salida.get("plan"):
        salida["plan"] = plan_inicial(conoc, heroe=None)
    salida["oro"] = oro
    salida["fuente"] = "pantalla"
    if vision and vision.get("oro") is not None and oro is None:
        # El oro (dinero sin gastar) sale de la tira del HUD leída por visión. Es dato
        # de pantalla, no de broadcast: se publica con su edad y sin tocar las almas.
        oro = vision.get("oro")
        salida["oro"] = oro
        notas = list(salida.get("notas") or [])
        edad_v = vision.get("edad_s")
        notas.append("oro leído por visión"
                     + (f" hace {int(edad_v)} s" if isinstance(edad_v, (int, float)) else ""))
        salida["notas"] = notas
    if vision and vision.get("items_visibles") is not None:
        salida["items_visibles"] = vision.get("items_visibles")
    if inventario:
        salida["inventario"] = items
        salida["slots"] = dict(inventario.get("slots") or {})
        notas = list(salida.get("notas") or [])
        edad = inventario.get("edad_s")
        notas.append("inventario leído en la tienda por visión"
                     + (f" hace {int(edad)} s" if isinstance(edad, (int, float)) else ""))
        salida["notas"] = notas
    # Sin broadcast y sin inventario, pasado el arranque, recomendar una compra es
    # inventarse la partida. Con el inventario de la tienda sí se puede decidir.
    if t > 600 and not items:
        salida.update({
            "solo_reloj": True,
            "recomendaciones": [],
            "decision": None,
            "objetivo": None,
            "camino": [],
            "estado": {"estado": "INICIO",
                       "motivo": "sin broadcast: solo puedo leer el reloj",
                       "objetivo": None},
            "notas": ["sin broadcast no veo tu inventario ni los rivales; "
                      "abre Tab para el marcador o juega una partida con retransmisión"],
        })
    # `listo` viene del motor y con medio estado sale False; aquí sí hay datos
    # frescos de la pantalla, así que la cabecera no debe decir «sin partida».
    salida["listo"] = True
    # `modo` es lo que el panel necesita para no mentir: en SOLO_LOCAL hay datos
    # frescos de la pantalla pero ninguna afirmación sobre el meta del parche.
    salida["modo"] = "SOLO_LOCAL"
    if nota:
        salida["notas"] = list(salida.get("notas") or []) + [str(nota)[:200]]
    if latencias:
        salida["latencia"] = latencias
    servidor.EST.publicar(salida)
    return True


def publicar_apertura(conoc, heroe=None):
    """Build de apertura: los tres primeros ítems, sin inventar almas ni enemigos."""
    if not conoc:
        return False
    plan = []
    from . import apertura
    ids_apertura = apertura.ids(heroe, 5)
    fuente_apertura = apertura.fuente(heroe)
    for iid in ids_apertura:
        d = conoc.get(iid) or {}
        if d:
            plan.append({"id": iid, "nombre": d.get("nombre", iid),
                         "costo": d.get("costo"), "n": 0, "icono": f"/icono/{iid}"})
    # En el menú no se está iniciando ninguna partida: decirlo cambia el panel de
    # «partida iniciando» (que suena a avería) a «en el menú, esperando partida».
    fase, frescura_s, cerrado = None, None, False
    try:
        from .fuentes import log_juego
        fase, frescura_s = log_juego.estado_ui()
        cerrado = log_juego.cerrado()
    except Exception:                                        # noqa: BLE001
        pass
    en_menu = fase == "menu"
    sin_juego = cerrado or fase is None
    servidor.EST.publicar({
        "t": 0, "almas": None, "oro": None,
        # Sin `listo: False` la cabecera caía en el caso por defecto y decía «en vivo»
        # mientras la tarjeta decía «esperando partida»: el mismo payload, dos
        # historias distintas.
        "listo": False,
        "modo": "APERTURA",
        "mensaje": ("en el menú del juego" if en_menu else
                    "esperando al juego" if sin_juego else "partida iniciando"),
        "estado": {"estado": "INICIO",
                   "motivo": ("esperando al juego" if sin_juego
                              else "en el menú del juego" if en_menu
                              else "partida iniciando"),
                   "objetivo": "build de apertura"},
        "economia": {"mias": None, "media_enemiga": None, "delta_pct": None},
        "recomendaciones": [], "plan": plan, "fuente": "apertura",
        "fase_juego": fase or "desconocida",
        "fuente_apertura": fuente_apertura,
        "frescura_juego_s": round(frescura_s, 1) if frescura_s is not None else None,
        "notas": ["En el menú del juego: build de apertura lista para cuando entres"
                  if en_menu else
                  "Build de apertura mientras llega el broadcast"],
    })
    return True


def publicar_congelado(tick):
    """El stream se paró: se conserva lo último y se marca rancio.

    Antes publicaba `listo: False`, así que el panel cambiaba a «sin partida» y
    parecía que se había desconectado. Ahora mantiene la última foto (reloj, almas,
    ítems) y deja que la edad haga su trabajo: «datos congelados · hace N s».
    """
    ultimo, _ = servidor.EST.leer()
    datos = dict(ultimo) if isinstance(ultimo, dict) else {}
    datos.update({
        "listo": True,
        "rancio": True,
        "fuente": datos.get("fuente") or "en_vivo",
        "mensaje": ("el broadcast dejó de mandar datos (último tick "
                    f"{tick}); reintentando"),
    })
    servidor.EST.publicar(datos)


def publicar_fuera_de_partida(est, cuenta):
    """Espectando una partida donde no está tu cuenta: el reloj sirve, el resto no."""
    if cuenta:
        detalle = f"pero tu cuenta {cuenta} no está en ella"
    else:
        detalle = ("pero no sé cuál jugador eres: pasa --cuenta o --mi-heroe "
                   "si quieres el panel completo")
    servidor.EST.publicar({
        "listo": False,
        "mensaje": (f"la partida va {int(est.get('t', 0))//60}:"
                    f"{int(est.get('t', 0)) % 60:02d}, {detalle}"),
        "t": est.get("t"),
        "fuente": "en_vivo",
    })


def ajustar_con_hud(crudo, estado_hud, latencias, sin_hud):
    """Cambia reloj y oro del broadcast por los del HUD si la lectura es fresca.

    El broadcast llega 20-80 s tarde. Cuando el OCR falla un ciclo, el reloj publicado
    volvía al del TV y el panel daba un salto de ~80 s (medido el 2026-11-09). Por eso
    se guarda el desfase HUD-broadcast y se sigue aplicando unos segundos aunque la
    lectura de ese instante no llegue.
    """
    api_t = crudo.get("t") or 0
    edad_hud = time.time() - (estado_hud.get("ts") or 0.0)
    fresco = (not sin_hud and edad_hud < 8 and estado_hud.get("t") is not None)
    h_t = estado_hud.get("t")

    if fresco and abs(h_t - api_t) <= 180:
        _RELOJ_HUD["desfase"] = h_t - api_t
        _RELOJ_HUD["ts"] = time.time()
        crudo["t"] = h_t
        # Diferencia real entre lo que ve el jugador y lo que manda el TV de
        # Valve: es la latencia del broadcast, medida, no estimada.
        latencias["broadcast_s"] = round(h_t - api_t, 1)
        latencias["edad_hud_s"] = round(edad_hud, 2)
        latencias["lectura_ms"] = round(
            sum(x for x in (estado_hud.get("ms_reloj"),
                            estado_hud.get("ms_oro")) if x) or 0, 1)
        nota = f"HUD OCR: reloj {h_t//60}:{h_t%60:02d}"
    elif (not sin_hud and _RELOJ_HUD["desfase"] is not None
          and time.time() - _RELOJ_HUD["ts"] < 300):
        # Sin lectura nueva, pero el desfase sigue valiendo: mejor un reloj estable
        # con el desfase de hace 20 s que uno que salta 80 s atrás.
        crudo["t"] = api_t + _RELOJ_HUD["desfase"]
        nota = "reloj del broadcast + desfase del HUD"
    else:
        nota = "reloj del broadcast"

    h_oro = estado_hud.get("oro")
    api_oro = crudo["yo"].get("oro") or 0
    if (fresco and h_oro is not None and api_oro
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
        # Se agrega, no se reemplaza: antes borraba la nota del reloj y el pie del
        # panel perdía de dónde venía la hora (visto en partida el 2026-11-09).
        salida["notas"] = list(salida.get("notas") or []) + [
            f"{oro:,} almas sin gastar: faltan {objetivo['faltan']:,} para "
            f"{objetivo.get('nombre')}"]
    salida["oro"] = oro
