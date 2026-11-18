#!/usr/bin/env python3
"""Arranca el coach.  Uso:
    python3 run.py --fuente simulado     # demo sin juego
    python3 run.py --fuente ocr          # lectura de pantalla real
"""
import argparse, collections, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coach import diagnostico, servidor
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


def _arrancar_vision(a):
    """Cola y planificador de visión, o (None, None) si no se puede usar.

    Se apaga sola cuando no hay credencial o el primer proveedor no lee imágenes: la app
    tiene que funcionar igual sin visión, solo con menos datos.
    """
    if getattr(a, "sin_vision", False):
        print("visión: apagada a propósito (--sin-vision)")
        return None, None
    from coach.agente import proveedor as P
    from coach.agente import vision_cola
    from coach.fuentes import captura_bajo_demanda as cbd

    prov = P.RespaldoVision()
    if not prov.hay_clave():
        print("visión: no hay credencial para ningún proveedor con imágenes")
        return None, None
    # La cola se pide al módulo (singleton): así /api/vision informa de la misma que
    # trabaja y no de una copia vacía.
    from coach.agente import vision as vision_base
    from coach.agente import vision_tienda, vision_zonas

    def lector(jpeg, motivo="periodico"):
        """Tira del HUD para el reloj y el oro; recorte de la tienda para los ítems."""
        if motivo == "tienda":
            return vision_tienda.leer_jpeg(jpeg, prov, timeout_s=vision_base.TIMEOUT_S)
        return vision_zonas.leer_jpeg(jpeg, prov, timeout_s=vision_base.TIMEOUT_S)
    cola = vision_cola.cola(proveedor=prov, lector=lector).arrancar()
    print(f"visión: {prov.nombre} · un cuadro cada "
          f"{getattr(a, 'vision_cada', 20.0):.0f} s")
    return cola, cbd.SchedulerVision(cola, intervalo_s=getattr(a, "vision_cada", 25.0),
                                     modo=getattr(a, "vision_modo", "tira"))


def disparo_por_compra(oro_previo, oro_actual, items_previos=None, items_actuales=None):
    """¿Acaba de comprar o vender? Entonces toca leer la tienda ya.

    Comprar baja el oro de golpe (el ítem más barato son 800) y cambia la rejilla de
    ítems. Con la cadencia fija de tienda se llegaba tarde: Diego abría B, compraba y
    cerraba. Con esta señal, la lectura sale en cuanto se ve el gasto.
    """
    if isinstance(oro_previo, int) and isinstance(oro_actual, int):
        if oro_previo - oro_actual >= 500:
            return "tienda"
    if isinstance(items_previos, int) and isinstance(items_actuales, int):
        if items_actuales != items_previos:
            return "tienda"
    return None


_MEMORIA_VISION = {"oro": None, "items_visibles": None}

# Cada cuánto se reintenta la URL del TV cuando no se pudo resolver. Sin URL no se abre
# el stream (abrir por `match_id` especta y gasta cuota); 60 s basta para recuperarse de
# un 5xx pasajero sin castigar el límite de 6/hora. Ver docs/api-vivo-sin-vision.md.
URL_REINTENTO_S = 60.0


def _resolver_url_tv(match):
    """URL del TV de la partida, o None. Nunca lanza: la ausencia es un caso normal."""
    try:
        from coach.fuentes import live_api
        return live_api.url_broadcast(int(match))
    except Exception as exc:                                   # noqa: BLE001
        print(f"  sin URL del TV: {type(exc).__name__}: {exc}")
        return None


def _sin_cuota(match):
    """La API ya negó el espectáculo de esa partida: no tiene sentido reintentar."""
    try:
        from coach.fuentes import live_api
        return live_api.sin_cuota(int(match))
    except Exception:                                          # noqa: BLE001
        return False


def _latido_vision(cola, sched, estado_hud):
    """Un paso de visión: guarda lo leído y decide si manda otro cuadro.

    Devuelve el inventario listo para el panel (o None). No espera a la API: lee lo que
    haya y encola. El panel sigue pintando con el reloj del HUD mientras tanto.
    """
    if not cola:
        return None
    from coach import inventario_propio
    from coach.fuentes import captura_bajo_demanda as cbd

    ultimo = cola.ultimo()
    estado = ultimo.get("estado")
    if estado:
        if estado.get("espectando"):
            # Mirar la partida de otro no puede tocar tu inventario.
            pass
        elif estado.get("tienda_abierta") or estado.get("items"):
            inventario_propio.actualizar(
                estado.get("items") or [], estado.get("slots") or {},
                fuente="tienda" if estado.get("tienda_abierta") else "vision",
                confianza=estado.get("confianza") or 0.0)
    if estado is not None:
        # La tienda se mira más o menos según si estaba abierta la última vez.
        if "tienda_abierta" in estado:
            sched.ajustar_tienda(bool(estado.get("tienda_abierta")))
        # Y si acaba de comprar, se mira ya: la cadencia fija llegaba tarde.
        disparo = disparo_por_compra(_MEMORIA_VISION["oro"], estado.get("oro"),
                                     _MEMORIA_VISION["items_visibles"],
                                     estado.get("items_visibles"))
        _MEMORIA_VISION["oro"] = estado.get("oro")
        _MEMORIA_VISION["items_visibles"] = estado.get("items_visibles")
        if disparo:
            sched.quizas_encolar(disparo, fuerza=True)
    if estado_hud.get("t") is not None:
        sched.quizas_encolar(cbd.motivo_por_estado(estado))
    inventario = inventario_propio.como_estado()
    # Una lectura de hace dos minutos no vale para esta partida: el oro y el reloj
    # cambian todo el rato. Vieja = no se publica, y el panel sigue con el reloj del HUD.
    edad_vision = ultimo.get("edad_s")
    if isinstance(edad_vision, (int, float)) and edad_vision > 60:
        estado = None
    if estado is not None:
        # La tira trae números que el panel puede enseñar hoy: oro e ítems visibles.
        if isinstance(estado.get("oro"), int):
            estado = dict(estado, edad_s=edad_vision)
        if inventario is None and isinstance(estado.get("oro"), int):
            return {"vision": estado, "items_visibles": estado.get("items_visibles")}
    return inventario


def bucle_vivo(a, analizar):
    """Modo en vivo: deadlock-api + HUD por OCR para reloj y oro en tiempo real."""
    from coach import en_vivo, registro
    estado_hud = arrancar_hud(a, _CFG["hud"], _CFG["flags"])
    cola_vision, sched_vision = _arrancar_vision(a)
    conoc = leer_conocimiento()
    def _modo_pantalla(mensaje):
        """Sin broadcast: publicar lo que sí se puede leer del HUD, con su nota.

        Devuelve True si publicó. Es el camino que impide que un 504 del CDN o una
        cuota agotada dejen el panel vacío con la partida en curso.
        """
        latido = _latido_vision(cola_vision, sched_vision, estado_hud)
        if not getattr(a, "pantalla", False):
            return False
        return bool(publicar_pantalla(
            estado_hud, analizar, medir_latencias(a), conoc,
            inventario=latido if (latido or {}).get("inventario") else None,
            vision=(latido or {}).get("vision"),
            nota=mensaje + " · sigo con la pantalla"))

    items_previos, heroes_cta, compras = {}, {}, []
    st = {"match": None, "escucha": None, "ultimo_hud": 0.0, "url_ts": 0.0,
          "tick": None, "tick_desde": time.time(), "avisado": False,
          "ultimo_vivo": 0.0, "arranque": time.time()}

    # El descubrimiento del id va aparte. Antes se llamaba aquí dentro y, cuando la API
    # entraba en pausa por cuota o tardaba, el bucle entero se quedaba esperando: el
    # panel decía «sin partida» con la partida en curso y el reloj del HUD mudo
    # (visto en ranked real el 2026-11-09).
    def _descubrir():
        import threading as _th
        while True:
            # Sin juego abierto no hay nada que descubrir y seguir preguntando a la API
            # cada 20 s gasta cuota a cambio de nada (medido: 5.5 % de un núcleo de CPU
            # y una petición cada 20 s con el juego cerrado). Se sondea cada minuto y
            # solo si el proceso del juego está vivo.
            if not juego_abierto():
                ultimo_cerrado = st.get("sin_juego") or 0.0
                if time.time() - ultimo_cerrado < 60.0:
                    _th.Event().wait(5.0)
                    continue
                st["sin_juego"] = time.time()
            try:
                hallado = buscar_match(a, st)
                if hallado:
                    st["match_descubierto"] = hallado
            except Exception as exc:                      # noqa: BLE001
                st["descubrimiento"] = {"via": None,
                                        "detalle": f"descubrimiento falló: {exc}"}
            _th.Event().wait(20.0)

    threading.Thread(target=_descubrir, daemon=True).start()
    while True:
        try:
            match = a.match or st.get("match_descubierto")
            if match is None:
                # Sin id de partida no hay reloj que publicar: la lectura del HUD en
                # el menú o en una partida que la API no reconoce no es una partida.
                # Antes se publicaba esa pantalla y el panel parecía estar jugando.
                # Con la partida en marcha, el reloj del HUD sí es dato de partida:
                # se publica aunque el id todavía no se sepa.
                latido = _latido_vision(cola_vision, sched_vision, estado_hud)
                if (getattr(a, "pantalla", False) and publicar_pantalla(
                        estado_hud, analizar, medir_latencias(a), conoc,
                        inventario=latido if (latido or {}).get("inventario")
                        else None,
                        vision=(latido or {}).get("vision"))):
                    time.sleep(max(1.0, a.intervalo))
                    continue
                # Mientras el descubrimiento del id sigue en curso no se anuncia
                # «apertura»: parpadeaba a los 0 s y a los 3 s cambiaba a la partida
                # real. A los 6 s sin noticias ya es una respuesta.
                if time.time() - st["arranque"] < 6.0:
                    time.sleep(1.0)
                    continue
                if publicar_apertura(conoc, heroe=getattr(a, "mi_heroe", None)):
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
                    st["escucha"] = None
                # La URL del TV se resuelve UNA vez por partida y queda cacheada en
                # `live_api` (memoria y disco): con ella la consulta no especta, así que
                # la cuota de los 6 espectáculos/hora se gasta una vez y no en cada
                # reconexión. Ver docs/api-vivo-sin-vision.md (medido el 2026-11-09).
                url_tv = _resolver_url_tv(match)
                st["match"] = match
                st["url_ts"] = time.time()
                if url_tv is None:
                    # Sin URL, el stream se abriría por `match_id` y ESO ESPECTA. El
                    # 2026-11-18 un 504 de la API hizo fallar la resolución, la escalera
                    # abrió cinco veces en un minuto y se llevó la cuota de la hora.
                    # Se sigue con HUD y console.log (gratis) y se reintenta la URL.
                    st["tick"], st["tick_desde"], st["avisado"] = (
                        None, time.time(), False)
                    olvidar_reloj_hud()
                    mensaje = ("sin URL del TV para la partida " + str(match)
                               + ": no se abre el stream para no gastar la "
                                 "cuota de espectador")
                    if _modo_pantalla(mensaje):
                        time.sleep(max(1.0, a.intervalo))
                        continue
                    servidor.EST.publicar({"listo": False, "mensaje": mensaje,
                                           "modo": "CIEGO", "fuente": "en_vivo"})
                    time.sleep(10.0)
                    continue
                print(f"partida en vivo: {match} · TV {url_tv.rsplit('/', 1)[-1]}")
                st["escucha"] = en_vivo.Escucha(
                    match, cuenta=a.cuenta, heroe=getattr(a, "mi_heroe", None),
                    url_tv=url_tv).arrancar()
                olvidar_reloj_hud()
                st["tick"], st["tick_desde"], st["avisado"] = None, time.time(), False

            # Partida conocida pero sin stream: se reintenta la URL del TV sin volver a
            # descubrir la partida. Ni antes de 60 s ni antes de lo que pida un 429: cada
            # reintento dentro de la ventana cuenta otra vez y mantiene la cuota agotada
            # para siempre (la escalera del 2026-11-18 lo demostró).
            if st["escucha"] is None and st.get("match") is not None:
                pausa = en_vivo.pausa_restante_s()
                if (not _sin_cuota(st["match"])
                        and time.time() - st.get("url_ts", 0.0) >= max(URL_REINTENTO_S,
                                                                      pausa)):
                    st["url_ts"] = time.time()
                    url_tv = _resolver_url_tv(st["match"])
                    if url_tv is not None:
                        print(f"partida en vivo: {st['match']}"
                              f" · TV {url_tv.rsplit('/', 1)[-1]}")
                        st["escucha"] = en_vivo.Escucha(
                            st["match"], cuenta=a.cuenta,
                            heroe=getattr(a, "mi_heroe", None),
                            url_tv=url_tv).arrancar()
                        st["tick"], st["tick_desde"], st["avisado"] = (
                            None, time.time(), False)
                if st["escucha"] is None:
                    pausa = en_vivo.pausa_restante_s()
                    if pausa > 0:
                        mensaje = (f"cuota de espectador: la API pidió esperar "
                                   f"{int(pausa)} s")
                    elif _sin_cuota(st["match"]):
                        mensaje = (f"cuota agotada para la partida {st['match']}: no se "
                                   "reintenta (cada intento gasta otra petición); "
                                   "se sigue con el HUD")
                    else:
                        mensaje = (f"sin URL del TV para la partida {st['match']}: "
                                   "se reintenta cada minuto y no se abre el stream "
                                   "para no gastar la cuota de espectador")
                    # Sin broadcast la app NO se apaga: el HUD sigue leyendo reloj,
                    # almas e inventario. Antes se publicaba listo=False y se saltaba
                    # el modo pantalla, así que un 504 de la API dejaba el panel vacío
                    # una hora aunque la partida estuviera en curso.
                    if _modo_pantalla(mensaje):
                        time.sleep(max(1.0, a.intervalo))
                        continue
                    servidor.EST.publicar({"listo": False, "mensaje": mensaje,
                                           "modo": "CIEGO", "fuente": "en_vivo"})
                    time.sleep(max(2.0, a.intervalo))
                    continue

            escucha = st["escucha"]
            est = escucha.estado
            # Cuota de espectador agotada: no es un fallo del panel ni de la partida.
            # Se dice con el tiempo de espera en vez de fingir datos de pantalla.
            if est is None and "esperar" in str(escucha.error or "").lower():
                servidor.EST.publicar({
                    "listo": False,
                    "mensaje": f"cuota de espectador: {escucha.error}",
                    "fuente": "en_vivo",
                })
                time.sleep(20.0)
                continue
            # El modo pantalla es el respaldo, no el principal: solo entra cuando el
            # broadcast lleva 15 s sin dar nada. Si no, el panel cambiaba de aspecto
            # cada pocos segundos (5 ítems del plan contra los del motor).
            sin_vivo = time.time() - st["ultimo_vivo"] > 15
            if est is None or not est.get("jugadores"):
                latido = _latido_vision(cola_vision, sched_vision, estado_hud)
                if (getattr(a, "pantalla", False) and sin_vivo and publicar_pantalla(
                        estado_hud, analizar, medir_latencias(a), conoc,
                        inventario=latido if (latido or {}).get("inventario")
                        else None,
                        vision=(latido or {}).get("vision"))):
                    time.sleep(max(1.0, a.intervalo))
                    continue
                if publicar_apertura(conoc, heroe=getattr(a, "mi_heroe", None)):
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
            # El motor solo tiene la ruta de Abrams: si el héroe es otro, se dice. La
            # apertura ya es del héroe correcto (coach/apertura.py), pero el camino,
            # los contras y los ítems siguen siendo de Abrams.
            heroe_jugado = (getattr(a, "mi_heroe", None) or (crudo.get("yo") or {})
                            .get("heroe") or "")
            if heroe_jugado and str(heroe_jugado).strip().lower() not in ("abrams", "6"):
                salida["aviso_heroe"] = f"motor solo Abrams · juegas {heroe_jugado}"
                # Con otro héroe el motor no puede puntuar (su economía es de Abrams),
                # pero sí se le da el camino observado de ese héroe por minuto.
                try:
                    from coach import camino_heroe
                    camino_heroe.aplicar_a_salida(salida, heroe_jugado)
                except Exception:                             # noqa: BLE001
                    pass
            salida["compras"] = list(compras)
            # Lo que el archivo local sabe de esta composición enemiga: «ya la jugaste,
            # así te fue». Sale del índice en disco (234 kB, se relee una vez por hora),
            # nunca de la red, así que no toca la cuota del API ni el ciclo del HUD.
            try:
                from coach import historico
                nombres_enemigos = [j.get("heroe") for j in crudo["enemigos"]]
                visto = historico.para_panel(nombres_enemigos)
                if visto:
                    salida["visto"] = visto
                # Y qué compran los que ganan contra estos héroes, por héroe y con
                # muestra: se exige que el ítem coincida en dos enemigos o más.
                from coach import items_comp
                traduccion = historico.nombre_a_id()
                ids_enemigos = [traduccion.get(str(n).strip().lower())
                                for n in nombres_enemigos if n]
                texto = items_comp.texto_sugerencia([i for i in ids_enemigos if i])
                if texto:
                    salida["sugerencia_items"] = texto
            except Exception:                                 # noqa: BLE001
                pass
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
            # Avisa al hilo del HUD de que el reloj ya viene por HTTP: así deja de
            # capturar la pantalla durante la partida (cada captura son ~29 ms).
            estado_hud["broadcast_ts"] = time.time()
        except Exception as exc:                                    # noqa: BLE001
            print(f"error en vivo: {type(exc).__name__}: {exc}", flush=True)
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
            img = a.imagen or lector.capturar(fuente=a.captura, devolver_imagen=True)
            lec = marcador.leer_captura(img, mi_heroe=mi_heroe,
                                           heroes=bool(mi_heroe))
            almas_12 = lec["almas"]["aliados"] + lec["almas"]["enemigos"]

            propias = lec.get("almas_propias")
            if propias is None and a.mi_columna is not None:
                propias = lec["almas"]["aliados"][a.mi_columna]
            if propias is None:
                # Solo pedir la columna si de verdad hay marcador. Antes se publicaba
                # «veo las 12 almas, no sé cuál eres tú» con cero almas leídas: en el
                # menú el panel afirmaba ver un marcador que no estaba (visto 2026-11-15).
                if lec.get("ok"):
                    publicar_sin_columna(lec, almas_12)
                else:
                    publicar_sin_marcador(lec)
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


# ------------------------------------------------------------------ modo OCR

def publicar_sin_marcador(lec):
    """No hay marcador legible: menú, cola, tienda o pantalla de fin.

    No es un error. La fase se lee del console.log del juego (`-condebug`), que cuesta
    un `stat`, sin capturar un solo píxel ni gastar API. Si el log no dice nada, se
    dice «no veo el marcador» y se sigue: jamás se afirma haber visto almas.
    """
    fase, frescura_s = None, None
    try:
        from coach.fuentes import log_juego
        fase, frescura_s = log_juego.estado_ui()
    except Exception:                                          # noqa: BLE001
        pass
    if fase == "partida":
        mensaje = "en partida, pero no veo tu marcador: abre Tab unos segundos"
    elif fase == "menu":
        mensaje = "en el menú del juego, esperando partida"
    else:
        mensaje = "no veo tu marcador (¿Tab apretado?)"
    servidor.EST.publicar({
        "listo": False,
        "mensaje": mensaje,
        "fase_juego": fase or "desconocida",
        "frescura_juego_s": round(frescura_s, 1) if frescura_s is not None else None,
        "tiempo_s": lec.get("tiempo_s"),
        "motivo_lectura": lec.get("motivo"),
    })


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
        # El motor mide el ritmo real de almas con estas muestras (ETA del panel).
        if isinstance(d, dict) and historial:
            d = {**d, "historial": list(historial)[-60:]}
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
    ap.add_argument("--captura", default="auto",
                    choices=["auto", "kwin", "bufer", "spectacle"],
                    help="fuente de imagen: KWin por región (por defecto), el búfer "
                         "de pantalla si está fresco, o spectacle como último recurso")
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
    ap.add_argument("--sin-vision", action="store_true",
                    help="no mandar cuadros al modelo (modo pantalla con reloj y oro)")
    ap.add_argument("--vision-cada", type=float, default=25.0,
                    help="segundos entre lecturas de visión")
    ap.add_argument("--vision-modo", default="tira", choices=["tira", "cuadro"],
                    help="tira = recorte del HUD (barato y correcto); cuadro = pantalla")
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
    # Si el bucle se cae sin traza, queda la señal o la excepción en
    # /tmp/abrams-coach-crash.log en vez de un proceso que desaparece en silencio.
    diagnostico.activar("coach")
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
