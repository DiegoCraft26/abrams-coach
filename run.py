#!/usr/bin/env python3
"""Arranca el coach.  Uso:
    python3 run.py --fuente simulado     # demo sin juego
    python3 run.py --fuente ocr          # lectura de pantalla real
"""
import argparse, collections, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coach import servidor
from coach.motor_api import Motor
from coach.estabilizador import Estabilizador
from coach.nucleo_demo import aviso_vram, estado_simulado, juego_abierto, leer_conocimiento
from coach.nucleo_vivo import (ajustar_con_hud, anotar_compras, arrancar_hud,
                               buscar_match, estado_desde_vivo, filtrar_por_oro,
                               medir_latencias, publicar_apertura, publicar_congelado,
                               publicar_fuera_de_partida, publicar_pantalla,
                               olvidar_reloj_hud)


_CFG = {"hud": {}, "flags": {}}   # lo llena configurar(), visible desde los bucles


def marcador_12(almas):
    """Las 12 almas fijadas a esa longitud: el panel indexa 0..11 sin sorpresas."""
    return (list(almas) + [None] * 12)[:12]


# ------------------------------------------------------------------ bucles

def bucle_simulado(a, analizar):
    """Demo sin juego: estado plausible que avanza según --acelerar."""
    t = float(a.t_inicial)
    while True:
        # si alguien inyecta un estado a mano, el demo se calla un rato
        if time.time() - servidor.EST.manual_ts > 120:
            crudo = estado_simulado(min(t, 2399))
            salida = analizar(crudo)
            # El demo rellena el mismo campo de 12 almas que llenan el modo vivo y el
            # OCR: así la sección EQUIPO del panel se puede probar sin partida.
            salida["almas_12"] = marcador_12(
                [crudo["yo"].get("almas")] + [j.get("almas") for j in crudo["aliados"]]
                + [j.get("almas") for j in crudo["enemigos"]])
            servidor.EST.publicar(salida)
        if a.acelerar > 0:
            t += 20 * a.acelerar
            if t > 2400:
                t = 0
        time.sleep(max(0.2, a.intervalo))


def bucle_vivo(a, analizar):
    """Modo en vivo: deadlock-api + HUD por OCR para reloj y oro en tiempo real."""
    from coach import en_vivo, registro
    estado_hud = arrancar_hud(a, _CFG["hud"], _CFG["flags"])
    conoc = leer_conocimiento()
    items_previos, heroes_cta, compras = {}, {}, []
    st = {"match": None, "escucha": None, "ultimo_hud": 0.0,
          "tick": None, "tick_desde": time.time(), "avisado": False,
          "ultimo_vivo": 0.0}
    while True:
        try:
            match = buscar_match(a, st)
            if match is None:
                # Sin broadcast (ranked, práctica, bots) lo único que hay es la
                # pantalla: reloj y almas. Si el modo está encendido y hay lectura
                # fresca, se publica eso en vez del build de apertura.
                if getattr(a, "pantalla", False):
                    if publicar_pantalla(estado_hud, analizar, medir_latencias(a), conoc):
                        time.sleep(max(1.0, a.intervalo))
                        continue
                    # Con el modo pantalla encendido y el HUD ya leído alguna vez, no se
                    # publica el build de apertura: haría saltar el reloj a 0:00. El
                    # panel marca los datos como viejos por su cuenta.
                    if estado_hud.get("ts"):
                        time.sleep(max(1.0, a.intervalo))
                        continue
                if publicar_apertura(conoc):
                    time.sleep(3.0)
                    continue
                servidor.EST.publicar({"listo": False,
                                       "mensaje": (f"la cuenta {a.cuenta} no está en partida"
                                                   if a.cuenta else
                                                   "no hay partida en vivo: lee el HUD o "
                                                   "pasa --cuenta / --match")})
                time.sleep(10.0)
                continue
            if match != st["match"]:
                if st["escucha"]:
                    st["escucha"].parar()
                print(f"partida en vivo: {match}")
                st["escucha"] = en_vivo.Escucha(match, cuenta=a.cuenta,
                                              heroe=getattr(a, "mi_heroe", None)).arrancar()
                st["match"] = match
                olvidar_reloj_hud()
                st["tick"], st["tick_desde"], st["avisado"] = None, time.time(), False
            escucha = st["escucha"]
            est = escucha.estado
            # El modo pantalla es el respaldo, no el principal: solo entra cuando el
            # broadcast lleva 15 s sin dar nada. Si no, el panel cambiaba de aspecto
            # cada pocos segundos (5 ítems del plan contra los del motor).
            sin_vivo = time.time() - st["ultimo_vivo"] > 15
            if est is None or not est.get("jugadores"):
                if (getattr(a, "pantalla", False) and sin_vivo and publicar_pantalla(
                        estado_hud, analizar, medir_latencias(a), conoc)):
                    time.sleep(max(1.0, a.intervalo))
                    continue
                if publicar_apertura(conoc):
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
            if est.get("tick") != st["tick"]:
                st["tick"], st["tick_desde"], st["avisado"] = (
                    est.get("tick"), time.time(), False)
            else:
                # El stream existe pero no manda nada (una partida sin broadcast). Si
                # el modo pantalla está encendido, se sigue con lo que se ve en el HUD
                # en vez de dejar el panel clavado en «datos congelados».
                if (getattr(a, "pantalla", False) and sin_vivo and publicar_pantalla(
                        estado_hud, analizar, medir_latencias(a), conoc)):
                    time.sleep(max(1.0, a.intervalo))
                    continue
                if time.time() - st["tick_desde"] > 12 and not st["avisado"]:
                    publicar_congelado(st["tick"])
                    st["avisado"] = True
                time.sleep(max(1.0, a.intervalo))
                continue
            if not est.get("yo"):
                # Espectando una partida donde no está tu cuenta: el reloj sirve, pero
                # no hay "yo" ni equipos. Mejor decirlo que mostrar un panel vacío.
                publicar_fuera_de_partida(est, a.cuenta)
                time.sleep(max(1.0, a.intervalo))
                continue
            crudo = estado_desde_vivo(est, a.cuenta)
            latencias = medir_latencias(a)
            ajustar_con_hud(crudo, estado_hud, latencias, getattr(a, "sin_hud", False))
            anotar_compras(est, conoc, items_previos, heroes_cta, compras)
            salida = analizar(crudo)
            salida["latencia"] = latencias
            salida["compras"] = list(compras)
            registro.anotar(salida, crudo)
            filtrar_por_oro(salida, crudo)
            # Las 12 almas del marcador, en el mismo campo que usa el modo OCR, para
            # que los dos paneles muestren lo mismo sin importar la fuente.
            salida["almas_12"] = marcador_12(
                [crudo["yo"].get("almas")]
                + [j.get("almas") for j in crudo["aliados"]]
                + [j.get("almas") for j in crudo["enemigos"]])
            servidor.EST.publicar(salida)
            st["ultimo_vivo"] = time.time()      # hubo broadcast: el respaldo no entra
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
                publicar_sin_columna(lec, almas_12)
                time.sleep(max(0.2, a.intervalo))
                continue

            estado = estado_desde_ocr(lec, a, propias)
            salida = analizar(estado)
            salida["almas_12"] = almas_12
            servidor.EST.publicar(salida)
            if salida.get("recomendaciones"):
                registro.anotar(salida, estado)
        except Exception as exc:                                    # noqa: BLE001
            servidor.EST.publicar({"listo": False, "mensaje": f"error de lectura: {exc}"})
        time.sleep(max(0.2, a.intervalo))


def bucle_auto(a, analizar):
    """Siempre el bucle en vivo: broadcast si lo hay, pantalla si no.

    Antes decidía una sola vez al arrancar y, si lo abrías en el menú del juego (sin
    partida todavía), se quedaba en el lector de marcador para siempre. Ahora no hay
    decisión que tomar: `bucle_vivo` busca el id en el HUD, engancha el broadcast si
    existe y, si no, publica reloj y plan de apertura desde la pantalla. Es lo que
    necesita el arranque automático de `abrams-coach esperar`.
    """
    print("automático: HUD y broadcast si hay partida; si no, pantalla")
    bucle_vivo(a, analizar)


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
                publicar_sin_columna(lec, almas_12)
                time.sleep(max(0.2, a.intervalo))
                continue

            estado = estado_desde_ocr(lec, a, propias)
            salida = analizar(estado)
            salida["almas_12"] = almas_12
            servidor.EST.publicar(salida)
            if salida.get("recomendaciones"):
                registro.anotar(salida, estado)
        except Exception as exc:                                    # noqa: BLE001
            servidor.EST.publicar({"listo": False, "mensaje": f"error de lectura: {exc}"})
        time.sleep(max(0.2, a.intervalo))


def bucle_auto(a, analizar):
    """Decide al arrancar: broadcast si tu cuenta está en partida, si no OCR.

    Si tu cuenta está en una partida, el broadcast da todo (almas por jugador,
    héroes, KDA) sin depender del marcador; si no, se lee la pantalla como siempre.
    """
    from coach import en_vivo
    if a.cuenta is None:
        # Sin cuenta no se puede preguntar "¿está mi cuenta en partida?", pero sí se
        # puede leer el MATCH del HUD y enganchar el broadcast a esa partida.
        print("automático: sin cuenta -> match_id del HUD y respaldo por pantalla")
        bucle_vivo(a, analizar)
        return
    match = a.match or en_vivo.partida_activa(a.cuenta)
    if match:
        print(f"automático: partida en vivo {match} -> broadcast")
        a.match = match
        bucle_vivo(a, analizar)
    else:
        print("automático: sin partida en vivo -> lectura por pantalla")
        bucle_ocr(a, analizar)


# ------------------------------------------------------------------ modo OCR

def publicar_sin_columna(lec, almas_12):
    """Ve el marcador pero no sabe cuál de las 12 almas sos vos: pide el dato."""
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


def estado_desde_ocr(lec, a, propias):
    """Estado en el formato del motor a partir de la lectura del marcador."""
    notas = []
    if lec["tiempo_s"] is None:
        notas.append("no leí el reloj")
    if not lec["ok"]:
        notas.append(lec["motivo"])
    notas.append("no leo tus ítems ni la composición por OCR "
                 "(pendiente: requiere captura de partida normal)")
    return {
        "t": lec["tiempo_s"] or 0,
        "yo": {"heroe": a.mi_heroe or "Abrams", "almas": propias, "items": []},
        "aliados": [{"almas": x} for i, x in enumerate(lec["almas"]["aliados"])
                    if i != (a.mi_columna if a.mi_columna is not None else -1)],
        "enemigos": [{"almas": x} for x in lec["almas"]["enemigos"]],
        "confianza": round(float(lec["confianza"]), 2),
        "fuente": "ocr",
        "notas": notas,
    }


# ------------------------------------------------------------------ arranque

def crear_analizador(m):
    """Motor + estabilizador + historial: lo único que un bucle necesita."""
    est = Estabilizador()
    historial = collections.deque(maxlen=240)

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
            salida["almas_12"] = marcador_12(
                [e.yo.almas] + [j.almas for j in e.aliados]
                + [j.almas for j in e.enemigos])
        return salida

    return analizar


def configurar(a):
    """Configuración con defaults y validación (config/coach.yaml).

    Si el archivo falta o está roto, `cargar()` devuelve los valores por defecto y
    anota el aviso: el coach nunca deja de arrancar por un YAML. Devuelve la config
    del motor.
    """
    # El aviso de "datos congelados" tiene que ser más lento que la cadencia real de
    # publicación, o con --intervalo alto el panel parpadearía sin nada roto.
    servidor.UMBRAL_RANCIO_S = max(8.0, 3.0 * max(0.2, a.intervalo))

    from coach.config import cargar
    cfg = cargar()
    _CFG["flags"] = cfg.flags
    _CFG["hud"] = (cfg.fuentes or {}).get("hud") or {}
    cfg_motor = dict(cfg.motor)
    if not cfg.flags.get("patrones_nuevos", True):
        # Rollback de los patrones nuevos sin tocar código.
        cfg_motor.update({"w_presupuesto": 0.0, "w_recuperacion": 0.0,
                          "w_balance": 0.0, "contexto_activo": False})
    if cfg.avisos:
        print("  avisos de config: " + "; ".join(cfg.avisos[:3]))
    return cfg_motor


def leer_argumentos():
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
    ap.add_argument("--cuenta", type=int,
                    default=(int(os.environ["ABRAMS_CUENTA"])
                             if os.environ.get("ABRAMS_CUENTA", "").isdigit() else None),
                    help="tu SteamID64 (opcional: sin ella el match_id sale del HUD; "
                         "también se lee de la variable ABRAMS_CUENTA)")
    ap.add_argument("--match", type=int, default=None,
                    help="match_id directo (en vez de buscarlo por cuenta)")
    ap.add_argument("--pantalla", action="store_true",
                    help="sin broadcast, lee reloj y almas de tu propia pantalla")
    ap.add_argument("--sin-hud", action="store_true",
                    help="no leer reloj/almas del HUD por OCR (usa solo el broadcast)")
    ap.add_argument("--mi-heroe", default=None,
                    help="héroe propio para identificar tu columna en el marcador")
    ap.add_argument("--mi-columna", type=int, default=None, choices=range(6),
                    help="columna aliada (0-5) que eres tú, si el héroe no se detecta")
    ap.add_argument("--imagen", default=None,
                    help="en modo ocr, leer esta captura en vez de la pantalla "
                         "(para probar sin el juego abierto)")
    # La cuenta es opcional a propósito. Sin ella, el match_id sale del HUD (capa 1 de
    # `api_vivo.descubrir`), así que el panel se monta sobre cualquier ranked sin pedir
    # el SteamID. Con `--mi-heroe` se intenta identificar tu columna por héroe; con
    # `--cuenta` se identifica sin ambigüedad. Nada de cuentas de fábrica: el repo es
    # público y una cuenta por defecto sería un dato personal.
    return ap.parse_args()


def main():
    a = leer_argumentos()
    # En vivo, el modo pantalla va encendido: es el único que sirve en ranked, práctica
    # y bots, donde Valve no retransmite nada. `--sin-hud` lo apaga junto con el OCR.
    if a.fuente in ("vivo", "auto") and not a.sin_hud:
        a.pantalla = True

    if a.fuente in ("ocr", "vivo", "auto"):
        aviso_vram()

    cfg_motor = configurar(a)

    # El arte de Deadlock no se distribuye: se baja del bucket público la primera vez,
    # sin retrasar el panel. Mientras llega, los componentes usan iconos de respaldo.
    from coach import iconos
    iconos.en_segundo_plano()

    print("cargando conocimiento…")
    m = Motor(cfg=cfg_motor)
    print(f"  {len(m.conoc['items'])} ítems · {len(m.conoc['pares'])} pares · "
          f"{len(m.conoc['counters'])} matchups")

    analizar = crear_analizador(m)
    servidor.arrancar(a.puerto, analizador=analizar)
    print(f"panel: http://127.0.0.1:{a.puerto}")

    if a.fuente == "simulado":
        bucle_simulado(a, analizar)
    elif a.fuente == "vivo":
        bucle_vivo(a, analizar)
    elif a.fuente == "auto":
        bucle_auto(a, analizar)
    else:
        bucle_ocr(a, analizar)


if __name__ == "__main__":
    main()
