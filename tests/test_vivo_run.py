"""El estado que se manda al panel desde el modo vivo.

Regresión del 2026-11-07: `estado_desde_vivo` tenía que repartir aliados/enemigos por
cuenta, sacarme de la lista de aliados y no inventar equipos si mi cuenta no está en la
partida. Se verificó contra una partida real; esto lo deja fijado sin red.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import run as R  # noqa: E402

HECHOS = {}


def probar(nombre, condicion, detalle=""):
    HECHOS[nombre] = bool(condicion)
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")


def estado_de_prueba():
    jugadores = []
    for i in range(12):
        jugadores.append({
            "cuenta": 5000 + i,
            "equipo": 2 if i < 6 else 3,
            "heroe": "Abrams" if i == 0 else f"heroe{i}",
            "almas": 1000 + 100 * i,
            "neto": 2000 + 100 * i,
            "bajas": i, "muertes": 1, "asistencias": 2,
        })
    yo = jugadores[0]
    return {"tick": 1000, "t": 15.6, "jugadores": jugadores, "yo": yo,
            "aliados": [j for j in jugadores if j["equipo"] == 2],
            "enemigos": [j for j in jugadores if j["equipo"] == 3]}


def main():
    print("estado desde el modo vivo")
    est = estado_de_prueba()
    d = R.estado_desde_vivo(est, cuenta=5000)

    probar("el tiempo pasa tal cual", d["t"] == 15.6, str(d["t"]))
    probar("mis almas son las mías", d["yo"]["almas"] == 1000, str(d["yo"]["almas"]))
    probar("mi héroe se conserva", d["yo"]["heroe"] == "Abrams")
    probar("no me cuento como aliado", len(d["aliados"]) == 5, str(len(d["aliados"])))
    probar("los enemigos son 6", len(d["enemigos"]) == 6, str(len(d["enemigos"])))
    probar("ningún aliado es mi cuenta",
           all(j.get("almas") != 1000 for j in d["aliados"]))
    probar("los enemigos traen almas",
           all(j.get("almas") is not None for j in d["enemigos"]))
    probar("KDA hacia el panel", d["yo"]["bajas"] == 0 and d["yo"]["asistencias"] == 2)
    probar("fuente marcada", d["fuente"] == "en_vivo")
    probar("confianza alta sin OCR", d["confianza"] >= 0.9)

    # sin "yo" en el estado (lo que devuelve el parser cuando tu cuenta no está en la
    # partida) no se debe inventar un jugador propio
    sin_yo = {k: v for k, v in est.items() if k != "yo"}
    d3 = R.estado_desde_vivo(sin_yo, cuenta=5000)
    probar("sin yo no se inventa un jugador", d3["yo"]["almas"] is None)
    probar("sin yo no hay héroe", d3["yo"]["heroe"] is None)
    probar("sin yo el tiempo igual sirve", d3["t"] == 15.6)

    # las 12 almas que arma bucle_vivo
    salida = dict(d)
    salida["almas_12"] = ([d["yo"].get("almas")] + [j.get("almas") for j in d["aliados"]]
                          + [j.get("almas") for j in d["enemigos"]])
    probar("12 almas en el panel", len(salida["almas_12"]) == 12,
           str(len(salida["almas_12"])))
    probar("12 almas sin huecos", all(a is not None for a in salida["almas_12"]))

    fallos = [k for k, v in HECHOS.items() if not v]
    print()
    if fallos:
        print(f"vivo_run: {len(fallos)} fallos -> {fallos}")
        return 1
    print(f"vivo_run: OK ({len(HECHOS)} comprobaciones)")
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
