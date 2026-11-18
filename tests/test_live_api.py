"""live_api: caché de la URL del TV, parseo del SSE y traducción al motor. Sin red.

La red se falsea entera: `_get_json` y `_lineas` se sustituyen por dobles. Lo que se
prueba es lo que se rompe en silencio: que una partida gaste UN espectáculo y no seis,
que un grupo de filas a medias no se publique y que el formato final sea el del motor.
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.fuentes import live_api as LA  # noqa: E402

HECHOS = {}


def probar(nombre, condicion, detalle=""):
    HECHOS[nombre] = bool(condicion)
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")


def filas(tick, n=12, cuenta_base=5000):
    return [{"tick": tick, "m_unEconAccountID": cuenta_base + i,
             "m_iTeamNum": 2 if i < 6 else 3,
             "m_PlayerDataGlobal__m_iGold": 300 + i,
             "m_PlayerDataGlobal__m_iGoldNetWorth": 4000 + 100 * i,
             "m_PlayerDataGlobal__m_nHeroID": 10,
             "m_PlayerDataGlobal__m_iPlayerKills": i,
             "m_PlayerDataGlobal__m_iDeaths": 0,
             "m_PlayerDataGlobal__m_iPlayerAssists": 1,
             "m_PlayerDataGlobal__m_vecUpgrades": []} for i in range(n)]


def sse(lista):
    """Convierte filas en las líneas de un SSE tal como las manda la API."""
    salida = []
    for f in lista:
        salida.append("event: data\n")
        salida.append("data: " + json.dumps(f) + "\n")
        salida.append("\n")
    return salida


def main():
    print("live_api: URL cacheada, SSE y formato del motor")

    # La pausa de cuota vive en disco: si la app de verdad está esperando un 429, la
    # prueba no puede heredarla o todos los espectáculos falsos quedan bloqueados.
    from coach import en_vivo as _EV
    _EV._PAUSA_HASTA = 0.0

    # El cupo local es persistente a propósito: si la prueba heredara el balde de la
    # app real, todos los espectáculos falsos quedarían bloqueados sin cuota. Se
    # aísla en un directorio temporal y se reinicia.
    import tempfile
    from coach import cuota as _CU
    _CU.RUTA = os.path.join(tempfile.mkdtemp(prefix="abrams-cupo-"), "cupo.json")
    # La prueba hace varias llamadas de pago seguidas a propósito (para ver que la
    # segunda sale de caché y que un 429 marca la partida): el balde local se abre
    # para que el freno real no falsee el resultado.
    _CU.PERMISOS["espectador"]["capacidad"] = 1000.0
    _CU.reiniciar()

    # --- la URL se pide una sola vez por partida ---------------------------
    llamadas = {"url": 0, "json": None}
    original_get = LA._get_json
    original_url = dict(LA._cache_url)

    def falso_get(url, timeout=20.0):
        if url.endswith("/live/url"):
            llamadas["url"] += 1
            return {"broadcast_url": "http://tv/falsa", "match_id": 1}
        llamadas["json"] = url
        return [{"match_id": 2, "broadcast_url": "http://tv/dos"},
                {"match_id": 3, "broadcast_url": "http://tv/tres"},
                {"basura": True}]

    LA._get_json = falso_get
    LA._cache_url.clear()
    u1 = LA.url_broadcast(1)
    LA.url_broadcast(1)
    u3 = LA.url_broadcast(1, forzar=True)
    probar("devuelve la URL", u1 == "http://tv/falsa", str(u1))
    probar("la segunda vez sale de caché", llamadas["url"] == 2,
           f"llamadas al endpoint={llamadas['url']} (1 + forzar)")
    probar("forzar vuelve a pedir", u3 == "http://tv/falsa")
    probar("las métricas cuentan la caché", LA.metricas()["urls_de_cache"] >= 1,
           str(LA.metricas()["urls_de_cache"]))

    # Lo que está en el escaparate no se paga: ni una llamada a `live/url`.
    probar("lo listado se resuelve sin espectar", LA.url_broadcast(2) == "http://tv/dos")
    probar("lo listado no gastó `live/url`", llamadas["url"] == 2,
           f"llamadas al endpoint={llamadas['url']}")

    lista = LA.urls_en_vivo()
    probar("lista de URLs en vivo filtra basura",
           lista == {2: "http://tv/dos", 3: "http://tv/tres"}, str(lista))

    # --- la caché sobrevive a cerrar y abrir el coach ---------------------
    # Sin esto, cada reapertura de la app durante una partida gastaba otro de los seis
    # espectáculos por hora. Es el límite que Diego pidió no romper nunca.
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="abrams-cache-")
    ruta_original = LA.RUTA_CACHE_URL
    LA.RUTA_CACHE_URL = os.path.join(carpeta, "urls.json")
    try:
        LA._guardar_cache_url()
        probar("la caché se escribe en disco", os.path.exists(LA.RUTA_CACHE_URL))
        # "reinicio": memoria vacía, disco lleno, red caída.
        antes = dict(LA._cache_url)
        LA._cache_url.clear()

        def red_caida(url, timeout=20.0):
            raise AssertionError(f"no debió pedir la URL: {url}")

        LA._get_json = red_caida
        LA._cargar_cache_url()
        probar("tras reiniciar, la URL sale de disco sin tocar la red",
               LA.url_broadcast(1) == "http://tv/falsa", str(LA._cache_url.get(1)))
        probar("la caché del disco trae la partida entera",
               set(LA._cache_url) >= {1}, str(sorted(LA._cache_url)))
        # Una entrada vieja no debe servir: la URL caduca a la hora.
        with open(LA.RUTA_CACHE_URL, "w", encoding="utf-8") as f:
            json.dump({"7": ["http://tv/vieja", 0.0]}, f)
        LA._cache_url.clear()
        LA._cargar_cache_url()
        probar("una URL caducada no se reutiliza", 7 not in LA._cache_url,
               str(sorted(LA._cache_url)))
        # Una caché corrupta no puede romper el arranque.
        with open(LA.RUTA_CACHE_URL, "w", encoding="utf-8") as f:
            f.write("{no es json")
        LA._cache_url.clear()
        LA._cargar_cache_url()
        probar("caché corrupta se ignora en silencio", LA._cache_url == {},
               str(LA._cache_url))
    finally:
        LA.RUTA_CACHE_URL = ruta_original
        LA._cache_url.clear()
        LA._cache_url.update(antes)
        LA._get_json = falso_get


    # --- el SSE: dos ticks, el incompleto no gana --------------------------
    ticks = sse(filas(100, 12) + filas(101, 12) + filas(102, 4))
    LA._lineas = lambda url_api, timeout: iter(ticks)
    est = LA.instantanea(match_id=1)
    probar("toma el tick más completo", est and est["tick"] == 101,
           str(est and est["tick"]))
    probar("tiempo = tick/64", est and est["t"] == round(101 / 64.0, 1), str(est and est["t"]))
    probar("12 jugadores", est and len(est["jugadores"]) == 12,
           str(est and len(est["jugadores"])))
    probar("fuente api", est and est.get("fuente") == "api")
    probar("latencia anotada", est and isinstance(est.get("latencia_api_s"), float))

    # --- un solo tick a medias no se publica ------------------------------
    LA._lineas = lambda url_api, timeout: iter(sse(filas(200, 3)))
    probar("grupo incompleto -> None", LA.instantanea(match_id=1) is None)

    # --- error del servidor dentro del SSE --------------------------------
    LA._lineas = lambda url_api, timeout: iter(
        ['data: {"status":500,"error":"Failed to spectate match: k_eNotInGame"}\n'])
    probar("error del SSE -> None", LA.instantanea(match_id=1) is None)
    probar("el error queda anotado",
           "k_eNotInGame" in (LA.metricas()["ultimo_error"] or ""),
           str(LA.metricas()["ultimo_error"])[:60])

    # --- formato del motor ------------------------------------------------
    LA._lineas = lambda url_api, timeout: iter(sse(filas(640, 12)))
    motor = LA.estado_motor(1, cuenta=5000)
    probar("estado_motor trae yo", motor and motor["yo"]["almas"] == 4000,
           str(motor and motor["yo"]))
    probar("estado_motor trae enemigos", motor and len(motor["enemigos"]) == 6,
           str(motor and len(motor["enemigos"])))
    probar("estado_motor no repite mi cuenta",
           motor and all(j["heroe"] != "yo" for j in motor["aliados"]))
    probar("estado_motor dice de dónde viene", motor and motor["fuente"] == "api")

    # --- sin URL no hay estado y no se inventa ----------------------------
    LA._get_json = lambda url, timeout=20.0: (_ for _ in ()).throw(LA.ErrorApi(500, "k_eNotInGame"))
    LA._cache_url.clear()
    probar("sin URL -> None", LA.instantanea(match_id=999) is None)
    probar("sin URL no revienta estado_motor", LA.estado_motor(999) is None)

    LA._get_json = original_get
    LA._cache_url.clear()
    LA._cache_url.update(original_url)

    # --- Escucha acepta la URL ya resuelta y no especta -------------------
    from coach import en_vivo as EV

    e = EV.Escucha(134651996, url_tv="http://tv/falsa")
    probar("Escucha usa broadcast_url", "broadcast_url=" in e._url(),
           e._url()[:70])
    probar("Escucha no manda match_id si hay URL", "match_id=" not in e._url())
    e2 = EV.Escucha(134651996)
    probar("sin URL sigue pidiendo por id", "match_id=134651996" in e2._url(),
           e2._url()[-40:])

    # --- el escaparate gratuito se mira ANTES de espectar -----------------
    # Caso real del 2026-11-18: `live/url` devolvió 504, `url_tv` quedó en None y la
    # escalera de reconexión abrió cinco streams por `match_id` en 65 s, que sí espectan.
    # Se agotaron las 6/hora y el panel dijo «cuota agotada» durante una hora.
    import tempfile

    ruta_original = LA.RUTA_CACHE_URL
    LA.RUTA_CACHE_URL = os.path.join(tempfile.mkdtemp(prefix="abrams-urls-"), "urls.json")
    pedidas = []
    listadas = {134651996: "http://tv/134651996_abc"}

    def falso_get(url, timeout=20.0):
        if url.endswith("/v1/matches/live/urls"):
            return [{"match_id": k, "broadcast_url": v} for k, v in listadas.items()]
        pedidas.append(url)
        return {"broadcast_url": "http://tv/de-pago"}

    LA._get_json = falso_get
    LA._cache_url.clear()
    LA._cache_lista["urls"].clear()
    LA._cache_lista["ts"] = 0.0
    url = LA.url_broadcast(134651996)
    probar("lo listado no especta", url == "http://tv/134651996_abc" and not pedidas,
           f"url={url} pedidas={pedidas}")
    probar("lo listado se guarda en disco", os.path.exists(LA.RUTA_CACHE_URL))

    LA._cache_url.clear()
    url = LA.url_broadcast(999999)
    probar("lo no listado sí pide live/url",
           url == "http://tv/de-pago" and len(pedidas) == 1,
           f"url={url} pedidas={len(pedidas)}")

    # Un 504 en `live/url` no puede dejar el coach sin memoria del gasto.
    LA._get_json = lambda url, timeout=20.0: (_ for _ in ()).throw(
        LA.ErrorApi(429, '{"status":429,"error":{"type":"IP","quota":{"limit":6,'
                         '"period":3600},"requests":6,"remaining":0,'
                         '"next_request_in":672}}'))
    LA._cache_url.clear()
    LA._sin_cuota.clear()
    pausa_antes = EV._PAUSA_HASTA
    EV._PAUSA_HASTA = 0.0
    probar("429 no devuelve URL", LA.url_broadcast(424242) is None)
    probar("la partida queda marcada sin cuota", LA.sin_cuota(424242))
    q = LA.cuota_de_429(
        '{"status":429,"error":{"type":"IP","quota":{"limit":6,"period":3600},'
        '"requests":6,"remaining":0,"next_request_in":672}}')
    probar("429 parsea type/requests/espera",
           q.get("type") == "IP" and q.get("requests") == 6
           and q.get("next_request_in") == 672, str(q))

    # Un reintento dentro de la ventana vuelve a contar: el 429 tiene que apuntar la
    # pausa compartida, o el reintento por minuto mantiene la cuota agotada para siempre.
    pausas = []
    pausa_original = LA.en_vivo.anotar_pausa
    LA.en_vivo.anotar_pausa = lambda s: pausas.append(s)
    try:
        LA._cache_url.clear()
        LA._sin_cuota.clear()
        EV._PAUSA_HASTA = 0.0
        LA.url_broadcast(424242)
    finally:
        LA.en_vivo.anotar_pausa = pausa_original

    # Y una partida negada no se vuelve a pedir: cada intento suma otra petición.
    intentos = {"n": 0}

    def get_429(url, timeout=20.0):
        if url.endswith("/live/url"):
            intentos["n"] += 1
        raise LA.ErrorApi(429, '{"status":429,"error":{"type":"IP","quota":{"limit":6,'
                               '"period":3600},"requests":12,"remaining":0,'
                               '"next_request_in":376}}')

    LA._get_json = get_429
    LA._sin_cuota.clear()
    LA._cache_url.clear()
    EV._PAUSA_HASTA = 0.0
    for _ in range(3):
        LA.url_broadcast(777001)
    probar("una partida negada no se reintenta", intentos["n"] == 1, str(intentos["n"]))

    # Con la ventana por encima del límite no basta el `next_request_in` de 90 s.
    pausas_sat = []
    LA.en_vivo.anotar_pausa = lambda s: pausas_sat.append(s)
    try:
        LA._sin_cuota.clear()
        LA._cache_url.clear()
        EV._PAUSA_HASTA = 0.0
        LA.url_broadcast(777002)
    finally:
        LA.en_vivo.anotar_pausa = pausa_original
    probar("ventana saturada -> pausa larga",
           pausas_sat and pausas_sat[0] >= LA.PAUSA_SATURADA_S, str(pausas_sat))
    LA._sin_cuota.clear()
    EV._PAUSA_HASTA = pausa_antes
    probar("el 429 apunta la pausa de la API", pausas == [672], str(pausas))

    LA._get_json = original_get
    LA.RUTA_CACHE_URL = ruta_original
    LA._cache_url.clear()
    LA._cache_url.update(original_url)

    # --- sin URL no hay escalera de reconexión ----------------------------
    probar("sin URL la espera es 300 desde el primer intento",
           e2.especta and e2._espera(0) == EV.ESPERA_SIN_URL_S
           and e2._espera(1) == EV.ESPERA_SIN_URL_S,
           f"{e2._espera(0)} {e2._espera(1)}")
    probar("con URL la escalera sigue viva",
           not e.especta and (e._espera(0), e._espera(1), e._espera(2))
           == (5.0, 15.0, 45.0), f"{e._espera(0)} {e._espera(1)} {e._espera(2)}")

    # --- el cuerpo del 429 se lee una sola vez ----------------------------
    class Falso429:
        headers = {}

        def __init__(self):
            self.lecturas = 0

        def read(self):
            self.lecturas += 1
            return (b'{"type":"IP","quota":{"limit":6,"period":3600,'
                    b'"requests":6,"next_request_in":672}}')

    falso = Falso429()
    EV._segundos_para_reintentar(falso)
    EV._cuerpo_429(falso)
    probar("el cuerpo del 429 no se relee", falso.lecturas == 1, str(falso.lecturas))

    # --- la pausa sobrevive a un reinicio ---------------------------------
    # Reiniciar el coach durante un 429 olvidaba la espera y gastaba otra petición en el
    # arranque; la ventana de 6/hora nunca drenaba (2026-11-18: 6 -> 9 -> 12).
    ruta_pausa_original = EV.RUTA_PAUSA
    EV.RUTA_PAUSA = os.path.join(tempfile.mkdtemp(prefix="abrams-pausa-"), "pausa.json")
    pausa_previa = EV._PAUSA_HASTA
    try:
        EV._PAUSA_HASTA = 0.0
        EV.anotar_pausa(600)
        probar("la pausa se escribe en disco", os.path.exists(EV.RUTA_PAUSA))
        EV._PAUSA_HASTA = 0.0
        EV._cargar_pausa()
        probar("tras reiniciar la pausa sigue puesta",
               590 < EV.pausa_restante_s() <= 600, str(round(EV.pausa_restante_s())))
    finally:
        EV._PAUSA_HASTA = pausa_previa
        EV.RUTA_PAUSA = ruta_pausa_original

    # --- una partida negada también sobrevive al reinicio ----------------
    ruta_neg_original = LA.RUTA_NEGADAS
    LA.RUTA_NEGADAS = os.path.join(tempfile.mkdtemp(prefix="abrams-neg-"), "negadas.json")
    try:
        LA._sin_cuota.clear()
        LA._sin_cuota[139583953] = LA.time.time()
        LA._guardar_negadas()
        LA._sin_cuota.clear()
        LA._cargar_negadas()
        probar("la partida negada sobrevive al reinicio", LA.sin_cuota(139583953))
    finally:
        LA._sin_cuota.clear()
        LA.RUTA_NEGADAS = ruta_neg_original

    fallos = [k for k, v in HECHOS.items() if not v]
    print()
    if fallos:
        print(f"live_api: {len(fallos)} fallos -> {fallos}")
        return 1
    print(f"live_api: OK ({len(HECHOS)} comprobaciones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_suite():
    assert main() == 0
