"""Estado de partida EN VIVO desde deadlock-api, sin OCR y sin tocar el juego.

Por qué: leer el marcador por pantalla exige que el jugador mantenga Tab apretado, y a
11 px de alto la tipografía del juego es frágil. deadlock-api expone el broadcast de
espectador de Valve por HTTP: un stream SSE que devuelve, por jugador y en vivo, almas,
patrimonio, héroe, equipo y el tick de la partida (tick/64 = segundos de juego).

Coste: RAM de unos pocos KB y ninguna VRAM (es una conexión HTTP). Latencia medida
~20-25 s respecto del juego (es el retardo del propio TV de Valve), suficiente para
decidir una compra, no para reaccionar a un duelo.

Límites medidos el 2026-11-08 (docs/experto/api.md): sin API key son 6 espectáculos por
hora por IP, así que se abre UN stream por partida y se mantiene; si se corta se
reconecta con espera creciente y sin rendirse. Además TODAS las llamadas a la API pasan
por una puerta que deja pasar un golpe cada 3 s como mucho (`_abrir`) y respeta el
`retry-after`/`next_request_in` que devuelve el 429.

Verificado el 2026-11-07 contra partidas reales sin key: filas con
m_iGold 244..291, m_iGoldNetWorth 1044..1091 y heroID por jugador en una partida de
tick 9492 (~148 s de juego).

Esto NO lee memoria del proceso del juego, no inyecta y no hookea: es la misma vía por
la que se ve una partida en el cliente de espectador.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

BASE = "https://api.deadlock-api.com"
TICKS_POR_SEGUNDO = 64.0          # nominal del broadcast; medido 63.05 en 40 s

# Un golpe a la API cada 3 s como mucho, entre todos los hilos (stream + sondeos).
# Con más ritmo lo único que se consigue es gastar la cuota de 6/h antes de tiempo.
INTERVALO_MIN_GOLPE_S = 3.0

# Espera entre reconexiones del stream. No hay tope de intentos: rendirse deja al coach
# clavado en una partida muerta, que es peor que insistir. Pero cada intento gasta una
# de las 6 peticiones de espectador por hora, así que agotada la escalera se pasa a un
# sondeo lento: si la partida murió, no se quema la cuota; si sólo fue un corte, el
# primer reintento de la escalera lo recupera y el contador vuelve a cero.
ESPERAS_RECONEXION_S = (5.0, 15.0, 45.0)
ESPERA_SIN_DATOS_S = 300.0

# La API está detrás de un CDN que devuelve 403 al User-Agent de urllib. Con un
# User-Agent propio responde 200 (verificado: urllib 403 -> 200 con esta cabecera).
CABECERAS = {
    "User-Agent": "abrams-coach/1.0 (Linux; captura de pantalla local)",
    "Accept": "application/json, text/event-stream",
}

# Columnas del controlador de jugador que dan lo que necesita el coach.
COLUMNAS = {
    "cuenta": "m_unEconAccountID",
    "equipo": "m_iTeamNum",
    "almas": "m_PlayerDataGlobal__m_iGold",
    "neto": "m_PlayerDataGlobal__m_iGoldNetWorth",
    "heroe_id": "m_PlayerDataGlobal__m_nHeroID",
    "bajas": "m_PlayerDataGlobal__m_iPlayerKills",
    "muertes": "m_PlayerDataGlobal__m_iDeaths",
    "asistencias": "m_PlayerDataGlobal__m_iPlayerAssists",
    # Inventario: el broadcast manda los IDs como uint64 en hex little-endian.
    "items": "m_PlayerDataGlobal__m_vecUpgrades",
}

SQL = ("SELECT tick," + ",".join(f'"{c}"' for c in COLUMNAS.values())
       + " FROM CCitadelPlayerController")


class ErrorCuota(Exception):
    """La API pidió esperar antes de volver a llamarla (HTTP 429)."""


class Diario:
    """Últimos errores y señales de red, para que el panel pueda diagnosticar.

    Lo llena esta capa sola: el bucle del coach no tiene que avisar de nada.
    """

    def __init__(self, maximo=30):
        self._lock = threading.Lock()
        self._errores = deque(maxlen=maximo)
        self.conexiones = 0
        self.match = None
        self.tick = None
        self.ts_senal = None

    def error(self, texto):
        with self._lock:
            self._errores.append({"ts": round(time.time(), 1),
                                  "texto": str(texto)[:200]})

    def conexion(self, match=None):
        with self._lock:
            self.conexiones += 1
            if match is not None:
                self.match = int(match)

    def senal(self, match, tick):
        with self._lock:
            self.match = int(match)
            self.tick = int(tick)
            self.ts_senal = time.time()

    def resumen(self):
        with self._lock:
            edad = (round(time.time() - self.ts_senal, 1)
                    if self.ts_senal else None)
            return {"match": self.match, "tick": self.tick,
                    "edad_senal_s": edad, "conexiones": self.conexiones,
                    "errores": list(self._errores)[-8:]}


DIARIO = Diario()

# --- puerta de ritmo y de cuota ------------------------------------------------
_PUERTA = threading.Lock()
_ULTIMO_GOLPE = 0.0
_PAUSA_HASTA = 0.0          # instante hasta el que la API pidió no llamar


def pausa_restante_s():
    """Segundos que faltan para poder volver a llamar a la API (0 = vía libre)."""
    return max(0.0, _PAUSA_HASTA - time.time())


def _anotar_pausa(segundos):
    global _PAUSA_HASTA
    try:
        segundos = float(segundos)
    except (TypeError, ValueError):
        segundos = 60.0
    if segundos > 0:
        _PAUSA_HASTA = max(_PAUSA_HASTA, time.time() + segundos)


def _esperar_turno():
    """Deja pasar un golpe cada INTERVALO_MIN_GOLPE_S, o falla si hay cuota en pausa."""
    global _ULTIMO_GOLPE
    with _PUERTA:
        restante = pausa_restante_s()
        if restante > 0:
            raise ErrorCuota(f"la API pidió esperar {int(restante)} s")
        espera = _ULTIMO_GOLPE + INTERVALO_MIN_GOLPE_S - time.time()
        if espera > 0:
            time.sleep(espera)
        _ULTIMO_GOLPE = time.time()


def _segundos_para_reintentar(exc):
    """Lo que pide esperar un 429: `retry-after` o el `next_request_in` del cuerpo."""
    try:
        cabecera = exc.headers.get("retry-after") if exc.headers else None
        if cabecera:
            return float(cabecera)
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        cuerpo = json.loads(exc.read().decode("utf-8"))
    except Exception:                                          # noqa: BLE001
        return 60.0
    if isinstance(cuerpo, dict):
        for clave in ("next_request_in", "retry_after"):
            if cuerpo.get(clave) is not None:
                try:
                    return float(cuerpo[clave])
                except (TypeError, ValueError):
                    break
        cuota = cuerpo.get("quota") or {}
        if isinstance(cuota, dict) and cuota.get("next_request_in") is not None:
            try:
                return float(cuota["next_request_in"])
            except (TypeError, ValueError):
                pass
    return 60.0


def _abrir(url, timeout, extra=None):
    """Abre una petición con el ritmo controlado y el 429 convertido en ErrorCuota."""
    _esperar_turno()
    cabeceras = dict(CABECERAS)
    if extra:
        cabeceras.update(extra)
    peticion = urllib.request.Request(url, headers=cabeceras)
    try:
        return urllib.request.urlopen(peticion, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            espera = _segundos_para_reintentar(exc)
            _anotar_pausa(espera)
            DIARIO.error(f"429 de la API: cuota agotada, {int(espera)} s de espera")
            raise ErrorCuota(f"la API pidió esperar {int(espera)} s") from exc
        DIARIO.error(f"HTTP {exc.code} en {url.split('?')[0]}")
        raise


def _get_json(url, timeout=20):
    with _abrir(url, timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _heroes():
    """Mapa id -> nombre desde data/heroes.json (una vez)."""
    import os
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "heroes.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception:
        return {}
    salida = {}
    for clave, valor in crudo.items():
        if isinstance(valor, dict) and valor.get("id") is not None:
            salida[int(valor["id"])] = valor.get("nombre")
        elif isinstance(valor, dict) and valor.get("nombre"):
            try:
                salida[int(clave)] = valor["nombre"]
            except (TypeError, ValueError):
                continue
    return salida


def partida_activa(cuenta, timeout=20, unico=False):
    """Match_id de la partida en la que está esa cuenta Steam, o None.

    Si la cuenta no está jugando, `[]` y se devuelve None. Usa el mismo endpoint que la
    pestaña "watch" del cliente, así que también sirve para ver a cualquiera.
    `unico=True` añade un parámetro de cache-bust: la caché del CDN es de 120 s y sirve
    respuestas rancias (medido), así que de vez en cuando hay que pedirla de verdad.
    """
    parametros = {"account_ids": int(cuenta)}
    if unico:
        parametros["t"] = time.time_ns()
    url = f"{BASE}/v1/matches/active?" + urllib.parse.urlencode(parametros)
    try:
        datos = _get_json(url, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, ErrorCuota):
        return None
    if isinstance(datos, list) and datos:
        primero = datos[0]
        if isinstance(primero, dict):
            cuenta_txt = str(int(cuenta))
            for jugador in primero.get("players", []) or []:
                if str(jugador.get("account_id")) == cuenta_txt:
                    return primero.get("match_id")
            return primero.get("match_id")
    return None


def listado_activo(timeout=20, unico=False):
    """Partidas activas completas (~250 KB, medido 0.10-0.36 s; caché CDN 120 s)."""
    url = f"{BASE}/v1/matches/active"
    if unico:
        url += "?t=" + str(time.time_ns())
    try:
        datos = _get_json(url, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, ErrorCuota):
        return []
    return [m for m in datos if isinstance(m, dict)] if isinstance(datos, list) else []


def buscar_en_listado(cuenta, timeout=20, unico=False):
    """Capa 3: filtra el listado global en local por cuenta.

    Devuelve (match_id o None, cuántas partidas traía la lista).
    """
    cuenta_txt = str(int(cuenta))
    partidas = listado_activo(timeout=timeout, unico=unico)
    for partida in partidas:
        for jugador in partida.get("players") or []:
            if str(jugador.get("account_id")) == cuenta_txt:
                return partida.get("match_id"), len(partidas)
    return None, len(partidas)


def partidas_con_broadcast(timeout=20):
    """Match_ids con broadcast de verdad (~5.8 KB; no gasta cuota de espectador).

    Sirve para descartar un match_id que nunca va a streamear, sin abrir el SSE.
    """
    try:
        datos = _get_json(f"{BASE}/v1/matches/live/urls", timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, ErrorCuota):
        return set()
    if not isinstance(datos, list):
        return set()
    salida = set()
    for fila in datos:
        if isinstance(fila, dict) and fila.get("match_id") is not None:
            try:
                salida.add(int(fila["match_id"]))
            except (TypeError, ValueError):
                continue
    return salida


def _items_upgrades(valor):
    """IDs de ítems del broadcast: hex uint64 little-endian -> str decimal."""
    salida = []
    for h in valor or []:
        try:
            salida.append(str(int.from_bytes(bytes.fromhex(h), "little")))
        except (TypeError, ValueError):
            continue
    return salida


def interpretar(filas, cuenta=None, heroes=None):
    """Convierte filas del stream en un estado de partida.

    Las filas son por jugador y comparten el mismo tick. Devuelve un dict con
    `t`, `tick`, `jugadores`, y si hay `cuenta`, separa `aliados`/`enemigos` y marca `yo`.
    """
    heroes = heroes if heroes is not None else _heroes()
    if not filas:
        return None
    # El broadcast trae alguna entidad extra además de los 12 jugadores (observado:
    # 13 filas). Los equipos reales son 2 (Amber) y 3 (Sapphire); lo demás se descarta.
    filas = [f for f in filas if f.get("m_iTeamNum") in (2, 3)] or list(filas)
    # Cada jugador puede venir repetido (un tick distinto por fila). Se queda la fila
    # más nueva de cada cuenta: si no, dos ticks del stream darían 24 jugadores.
    por_cuenta = {}
    for f in filas:
        cuenta_j = f.get("m_unEconAccountID")
        tick_j = int(f.get("tick", 0))
        previo = por_cuenta.get(cuenta_j)
        if previo is None or tick_j >= int(previo.get("tick", 0)):
            por_cuenta[cuenta_j] = f
    filas = list(por_cuenta.values())
    if len(filas) > 12:
        # Si aún sobran, los reales son los que tienen patrimonio; un observador no.
        filas = sorted(filas, key=lambda f: (f.get("m_PlayerDataGlobal__m_iGoldNetWorth") or -1),
                       reverse=True)[:12]
    tick = max(int(f.get("tick", 0)) for f in filas)
    jugadores = []
    for f in filas:
        hid = f.get("m_PlayerDataGlobal__m_nHeroID")
        oro = f.get("m_PlayerDataGlobal__m_iGold")
        neto = f.get("m_PlayerDataGlobal__m_iGoldNetWorth")
        jugadores.append({
            "cuenta": f.get("m_unEconAccountID"),
            "equipo": f.get("m_iTeamNum"),
            # "almas" = patrimonio (lo que muestra el HUD como SOULS). m_iGold es el
            # oro sin gastar y compararlo entre jugadores da deltas falsos.
            "almas": neto if neto is not None else oro,
            "oro": oro,
            "neto": neto,
            "items": _items_upgrades(f.get("m_PlayerDataGlobal__m_vecUpgrades")),
            "heroe_id": hid,
            "heroe": heroes.get(int(hid)) if hid is not None else None,
            "bajas": f.get("m_PlayerDataGlobal__m_iPlayerKills"),
            "muertes": f.get("m_PlayerDataGlobal__m_iDeaths"),
            "asistencias": f.get("m_PlayerDataGlobal__m_iPlayerAssists"),
        })
    estado = {"tick": tick, "t": round(tick / TICKS_POR_SEGUNDO, 1),
              "jugadores": jugadores, "fuente": "en_vivo"}
    if cuenta is not None:
        cuenta_txt = str(int(cuenta))
        mio = next((j for j in jugadores if str(j["cuenta"]) == cuenta_txt), None)
        if mio is not None:
            estado["yo"] = mio
            estado["aliados"] = [j for j in jugadores if j["equipo"] == mio["equipo"]]
            estado["enemigos"] = [j for j in jugadores if j["equipo"] != mio["equipo"]]
    return estado


class Escucha:
    """Stream SSE en un hilo. Guarda el último estado y el error más reciente.

    Reintenta con espera creciente (5, 15, 45 s) y NO se rinde; agotada la escalera
    pasa a un sondeo lento de 300 s para no gastar la cuota de espectador en una
    partida muerta. Al volver a conectar, el contador se pone a cero. Quien eligió el
    match es el que tiene que soltarlo cuando deja de dar señal: eso lo hace el
    descubrimiento de `coach.fuentes.api_vivo` (90 s sin un solo estado).

    Uso:
        e = Escucha(match_id=123, cuenta=TU_STEAMID64)
        e.arrancar()
        ... e.estado          # dict o None
        ... e.edad_s()        # segundos desde el último estado
        e.parar()
    """

    def __init__(self, match_id, cuenta=None, sql=SQL, max_segundos=None):
        self.match_id = int(match_id)
        self.cuenta = cuenta
        self.sql = sql
        self.max_segundos = max_segundos
        self.estado = None
        self.error = None
        self.conectado = False
        self.filas = 0
        self.estados = 0             # estados publicados (para saber si sirvió conectar)
        self.reintentos = 0          # reconexiones hechas (para el diagnóstico)
        self.ts_estado = None
        self._parar = threading.Event()
        self._hilo = None
        self._heroes = _heroes()

    # ------------------------------------------------------------------ interno
    def _url(self):
        return (f"{BASE}/v1/matches/demo/live/query?"
                + urllib.parse.urlencode({"query": self.sql, "match_id": self.match_id}))

    def _espera(self, intento):
        if intento < len(ESPERAS_RECONEXION_S):
            return ESPERAS_RECONEXION_S[intento]
        return ESPERA_SIN_DATOS_S

    def _publicar(self, grupo):
        estado = interpretar(grupo, self.cuenta, self._heroes)
        if estado is None:
            return None
        self.estado = estado
        self.estados += 1
        self.ts_estado = time.time()
        DIARIO.senal(self.match_id, estado["tick"])
        return estado

    def _bucle(self):
        intento = 0
        arranque = time.time()
        while not self._parar.is_set():
            if self.max_segundos and time.time() - arranque > self.max_segundos:
                break
            estados_antes = self.estados
            try:
                with _abrir(self._url(), timeout=60,
                            extra={"Accept": "text/event-stream"}) as respuesta:
                    self.conectado = True
                    self.error = None
                    DIARIO.conexion(self.match_id)
                    tick_actual = -1
                    grupo = []
                    for linea in respuesta:
                        if self._parar.is_set():
                            break
                        texto = linea.decode("utf-8", "replace").strip()
                        if not texto.startswith("data:"):
                            continue
                        carga = texto[5:].strip()
                        if not carga or carga == "[DONE]":
                            continue
                        try:
                            fila = json.loads(carga)
                        except ValueError:
                            continue
                        if not isinstance(fila, dict):
                            continue
                        self.filas += 1
                        tick = int(fila.get("tick", 0))
                        if tick > tick_actual:
                            # Al llegar un tick nuevo, el anterior ya está completo:
                            # se publica entero (los 12 jugadores) y se empieza otro.
                            if grupo:
                                self._publicar(grupo)
                            tick_actual = tick
                            grupo = [fila]
                        elif tick == tick_actual:
                            grupo.append(fila)
                            # Si el tick no avanza (partida pausada o stream lento), el
                            # grupo nunca se publicaba. Con 12 filas ya hay estado válido.
                            if len(grupo) >= 12:
                                self._publicar(grupo)
                                if len(grupo) > 24:
                                    grupo = grupo[-24:]
                        # los ticks viejos se ignoran: al conectar el stream repite
                        # historial y no debe pisar el estado actual
            except ErrorCuota as exc:
                self.error = str(exc)
                DIARIO.error(f"stream {self.match_id}: {exc}")
                # La cuota manda: ni un reintento antes del instante que dijo la API.
                self._parar.wait(min(300.0, max(1.0, pausa_restante_s())))
                continue
            except urllib.error.HTTPError as exc:
                self.error = f"HTTP {exc.code} del stream"
                DIARIO.error(f"stream {self.match_id}: HTTP {exc.code}")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                DIARIO.error(f"stream {self.match_id}: {self.error}")
            finally:
                self.conectado = False
            if self._parar.is_set():
                break
            # La escalera vuelve a cero solo si esa conexión trajo algún estado: si el
            # servidor acepta y cierra sin datos (partida muerta), insistir cada 5 s
            # quema las 6 peticiones de espectador por hora.
            if self.estados > estados_antes:
                intento = 0
            self.reintentos += 1
            self._parar.wait(self._espera(intento))
            intento += 1

    # ------------------------------------------------------------------ público
    def arrancar(self):
        if self._hilo and self._hilo.is_alive():
            return self
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="en-vivo", daemon=True)
        self._hilo.start()
        return self

    def parar(self, espera=2.0):
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=espera)
        return self

    def vivo(self):
        return bool(self._hilo and self._hilo.is_alive())

    def edad_s(self):
        """Segundos desde el último estado publicado (None si nunca hubo)."""
        return None if self.ts_estado is None else round(time.time() - self.ts_estado, 1)

    def resumen(self):
        """Una línea para logs."""
        if self.estado is None:
            return f"en vivo: sin datos ({self.error or 'conectando'})"
        t = self.estado["t"]
        yo = self.estado.get("yo") or {}
        return (f"en vivo tick {self.estado['tick']} ({int(t)//60}:{int(t)%60:02d}) · "
                f"yo {yo.get('heroe')} {yo.get('almas')} almas · {self.filas} filas")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Estado en vivo de Deadlock (deadlock-api)")
    p.add_argument("--cuenta", type=int, help="SteamID64 para buscar tu partida")
    p.add_argument("--match", type=int, help="match_id directo")
    p.add_argument("--segundos", type=float, default=30.0)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    match = a.match
    if match is None:
        if a.cuenta is None:
            p.error("hace falta --cuenta o --match")
        match = partida_activa(a.cuenta)
        if match is None:
            print(f"la cuenta {a.cuenta} no está en ninguna partida activa")
            return 1
        print(f"partida activa: {match}")

    e = Escucha(match, cuenta=a.cuenta, max_segundos=a.segundos).arrancar()
    limite = time.time() + a.segundos
    visto = -1
    try:
        while time.time() < limite:
            time.sleep(1.0)
            if e.estado and e.estado["tick"] != visto:
                visto = e.estado["tick"]
                if a.json:
                    print(json.dumps(e.estado, ensure_ascii=False))
                else:
                    print(e.resumen())
    finally:
        e.parar()
    return 0 if e.estado else 1


if __name__ == "__main__":
    raise SystemExit(main())
