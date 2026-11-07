"""Estado de partida EN VIVO desde deadlock-api, sin OCR y sin tocar el juego.

Por qué: leer el marcador por pantalla exige que el jugador mantenga Tab apretado, y a
11 px de alto la tipografía del juego es frágil. deadlock-api expone el broadcast de
espectador de Valve por HTTP: un stream SSE que devuelve, por jugador y en vivo, almas,
patrimonio, héroe, equipo y el tick de la partida (tick/64 = segundos de juego).

Coste: RAM de unos pocos KB y ninguna VRAM (es una conexión HTTP). Latencia medida
~20-25 s respecto del juego (es el retardo del propio TV de Valve), suficiente para
decidir una compra, no para reaccionar a un duelo.

Límites: sin API key son 6 espectáculos por hora por IP, así que se abre UN stream por
partida y se mantiene; si se corta, se reconecta con espera creciente.

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

BASE = "https://api.deadlock-api.com"
TICKS_POR_SEGUNDO = 64.0          # nominal del broadcast; medido 63.05 en 40 s

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
}

SQL = ("SELECT tick," + ",".join(f'"{c}"' for c in COLUMNAS.values())
       + " FROM CCitadelPlayerController")


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


def _get_json(url, timeout=20):
    peticion = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(peticion, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def partida_activa(cuenta, timeout=20):
    """Match_id de la partida en la que está esa cuenta Steam, o None.

    Si la cuenta no está jugando, `[]` y se devuelve None. Usa el mismo endpoint que la
    pestaña "watch" del cliente, así que también sirve para ver a cualquiera.
    """
    url = f"{BASE}/v1/matches/active?" + urllib.parse.urlencode({"account_id": int(cuenta)})
    try:
        datos = _get_json(url, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError):
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
        jugadores.append({
            "cuenta": f.get("m_unEconAccountID"),
            "equipo": f.get("m_iTeamNum"),
            "almas": f.get("m_PlayerDataGlobal__m_iGold"),
            "neto": f.get("m_PlayerDataGlobal__m_iGoldNetWorth"),
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

    Uso:
        e = Escucha(match_id=123, cuenta=TU_STEAMID64)
        e.arrancar()
        ... e.estado  # dict o None
        e.parar()
    """

    def __init__(self, match_id, cuenta=None, sql=SQL, reintento=30.0,
                 tope_reintentos=3, max_segundos=None):
        self.match_id = int(match_id)
        self.cuenta = cuenta
        self.sql = sql
        self.reintento = reintento
        self.tope_reintentos = tope_reintentos
        self.max_segundos = max_segundos
        self.estado = None
        self.error = None
        self.conectado = False
        self.filas = 0
        self._parar = threading.Event()
        self._hilo = None
        self._heroes = _heroes()

    # ------------------------------------------------------------------ interno
    def _url(self):
        return (f"{BASE}/v1/matches/demo/live/query?"
                + urllib.parse.urlencode({"query": self.sql, "match_id": self.match_id}))

    def _bucle(self):
        intentos = 0
        arranque = time.time()
        while not self._parar.is_set():
            if self.max_segundos and time.time() - arranque > self.max_segundos:
                break
            try:
                peticion = urllib.request.Request(
                    self._url(),
                    headers={**CABECERAS, "Accept": "text/event-stream"})
                with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                    self.conectado = True
                    self.error = None
                    intentos = 0
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
                                estado = interpretar(grupo, self.cuenta, self._heroes)
                                if estado is not None:
                                    self.estado = estado
                            tick_actual = tick
                            grupo = [fila]
                        elif tick == tick_actual:
                            grupo.append(fila)
                        # los ticks viejos se ignoran: al conectar el stream repite
                        # historial y no debe pisar el estado actual
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self.error = f"{type(exc).__name__}: {exc}"
            finally:
                self.conectado = False
            if self._parar.is_set():
                break
            intentos += 1
            if intentos > self.tope_reintentos:
                break
            self._parar.wait(self.reintento * intentos)

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
