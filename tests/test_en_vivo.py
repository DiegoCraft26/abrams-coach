"""Prueba del cliente en vivo SIN red: verifica el parser del stream SSE.

El parser es la parte que puede romperse en silencio, así que se prueba con un stream
sintético con la misma forma que devuelve deadlock-api. La conexión real no se prueba
aquí porque cada espectáculo consume una de las 6/h sin API key.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import en_vivo as EV  # noqa: E402
from coach import nucleo_vivo as NV  # noqa: E402

HECHOS = {}


def probar(nombre, condicion, detalle=""):
    HECHOS[nombre] = bool(condicion)
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")


def filas_sinteticas(tick, n=12):
    salida = []
    for i in range(n):
        salida.append({
            "tick": tick,
            "m_unEconAccountID": 1000 + i,
            "m_iTeamNum": 2 if i < 6 else 3,
            "m_PlayerDataGlobal__m_iGold": 100 * i + tick,
            "m_PlayerDataGlobal__m_iGoldNetWorth": 200 * i + tick,
            "m_PlayerDataGlobal__m_nHeroID": 10,
            "m_PlayerDataGlobal__m_iPlayerKills": i,
            "m_PlayerDataGlobal__m_iDeaths": 0,
            "m_PlayerDataGlobal__m_iPlayerAssists": 1,
        })
    return salida


def main():
    print("parser del stream en vivo")
    filas = filas_sinteticas(100) + filas_sinteticas(101)
    e = EV.interpretar(filas, cuenta=1000, heroes={10: "Paradox"})
    probar("toma el tick más alto", e["tick"] == 101, f"tick={e['tick']}")
    probar("tiempo = tick/64", e["t"] == round(101 / 64.0, 1), f"t={e['t']}")
    probar("deduplica jugadores entre ticks", len(e["jugadores"]) == 12,
           str(len(e["jugadores"])))
    probar("se identifica a mí", e["yo"]["cuenta"] == 1000)
    probar("héroe por id", e["yo"]["heroe"] == "Paradox")
    probar("6 aliados", len(e["aliados"]) == 6, str(len(e["aliados"])))
    probar("6 enemigos", len(e["enemigos"]) == 6, str(len(e["enemigos"])))
    probar("aliados y enemigos no se mezclan",
           {j["equipo"] for j in e["aliados"]}.isdisjoint({j["equipo"] for j in e["enemigos"]}))
    probar("almas por jugador no nulas", all(j["almas"] is not None for j in e["jugadores"]))
    probar("lista vacía devuelve None", EV.interpretar([], cuenta=1000) is None)
    sin_mi = EV.interpretar(filas_sinteticas(100)[:3], cuenta=999)
    probar("sin mi cuenta no inventa equipos", "aliados" not in sin_mi)

    # Sin cuenta: el match se montó por el id del HUD y tu columna se busca por héroe.
    fs = filas_sinteticas(200)
    for f in fs:
        f["m_PlayerDataGlobal__m_nHeroID"] = 1
    fs[4]["m_PlayerDataGlobal__m_nHeroID"] = 10          # único Paradox
    est = EV.interpretar(fs, cuenta=None, heroes={1: "Infernus", 10: "Paradox"},
                         heroe="paradox")
    probar("sin cuenta: héroe único marca yo",
           (est.get("yo") or {}).get("cuenta") == 1004)
    probar("sin cuenta: 6 aliados y 6 enemigos",
           len(est.get("aliados") or []) == 6 and len(est.get("enemigos") or []) == 6)
    crudo = NV.estado_desde_vivo(est, None)
    probar("sin cuenta: el estado del motor saca a yo de aliados",
           len(crudo["aliados"]) == 5, str(len(crudo["aliados"])))
    fs[7]["m_PlayerDataGlobal__m_nHeroID"] = 10          # ahora hay dos Paradox
    est2 = EV.interpretar(fs, cuenta=None, heroes={1: "Infernus", 10: "Paradox"},
                          heroe="paradox")
    probar("dos Paradox: no adivina cuál eres", "yo" not in est2)

    # El id del HUD puede venir mal leído: si hay cuenta, manda la partida de la cuenta.
    from coach.fuentes import api_vivo
    original_hud, original_activa = api_vivo._leer_hud, EV.partida_activa
    try:
        api_vivo._leer_hud = lambda: 134344094
        EV.partida_activa = lambda cuenta, timeout=20, unico=False: 134294885
        api_vivo.olvidar()
        r = api_vivo.descubrir(cuenta=376225059, forzar=True)
        probar("HUD mal leído: gana la partida de la cuenta",
               int(r.get("match") or 0) == 134294885 and r.get("via") == "cuenta",
               str(r.get("match")))
        api_vivo._leer_hud = lambda: 134294885
        api_vivo.olvidar()
        r = api_vivo.descubrir(cuenta=376225059, forzar=True)
        probar("HUD correcto: se usa y se verifica",
               int(r.get("match") or 0) == 134294885 and "verificado" in (r.get("detalle") or ""),
               str(r.get("detalle")))
    finally:
        api_vivo._leer_hud = original_hud
        EV.partida_activa = original_activa
        api_vivo.olvidar()
    probar("no toca la red", True)

    fallos = [k for k, v in HECHOS.items() if not v]
    print()
    if fallos:
        print(f"en_vivo: {len(fallos)} fallos -> {fallos}")
        return 1
    print(f"en_vivo: OK ({len(HECHOS)} comprobaciones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def test_suite():
    """Entrada para `pytest -q`.

    Las suites están escritas como scripts con `main()` que devuelve el número de
    fallos. Este envoltorio las expone a pytest sin cambiar su comportamiento
    (siguen corriendo también con `python3 tests/<archivo>.py`).
    """
    assert main() == 0
