"""Banco de partidas como prueba: el motor sobre 12 partidas reales.

No es un test de rendimiento: es el guardarraíl de comportamiento. Si alguien cambia el
camino, los counters o el perfil y el coach empieza a decir «build completo», a recomendar
caro sin pedir ahorrar o a cambiar de objetivo solo con el reloj, esto lo caza sin abrir
el juego.

Se corre en pocos segundos porque usa 12 partidas y una muestra por minuto; el banco
completo (`herramientas/banco_partidas.py`) es para mirar los números, no para CI.
"""
import importlib.util
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

_fallos = []


def check(nombre, cond, detalle=""):
    print(f"  {'ok  ' if cond else 'FALLA'} {nombre}"
          f"{(' · ' + str(detalle)) if detalle else ''}")
    if not cond:
        _fallos.append(nombre)


def _banco():
    ruta = os.path.join(RAIZ, "herramientas", "banco_partidas.py")
    spec = importlib.util.spec_from_file_location("banco_partidas", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    import json

    banco = _banco()
    # El cache completo no se versiona: en un clon limpio se usa la muestra de 60
    # partidas, que es la que el CI trae. Si no hay ninguna de las dos, se salta.
    for candidata in ("replay_cache.json", "replay_muestra.json"):
        ruta = os.path.join(RAIZ, "data", candidata)
        if os.path.exists(ruta):
            break
    else:
        import pytest
        pytest.skip("sin data/replay_cache.json ni data/replay_muestra.json")
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)[:12]
    resultados = [banco.muestrear((p, 60, "parejo")) for p in datos]
    res = banco.agregar(resultados, 60)

    print("banco (12 partidas, 1 muestra/minuto)")
    check("no dice «build completo»", res["completos"] == 0, res["completos"])
    check("nunca recomienda caro sin pedir ahorrar", res["caro_sin_ahorrar"] == 0,
          res["caro_sin_ahorrar"])
    check("no recomienda 6400 antes del minuto 16", res["caros_pronto"] == 0,
          res["caros_pronto"])
    check("no cambia de objetivo solo por el reloj",
          res["pct_flips_solo_tiempo"] <= 5.0, f'{res["pct_flips_solo_tiempo"]}%')
    # La cobertura mide parecido con lo que compran los jugadores, no calidad: un build
    # distinto pero mejor baja este número. Se vigila que no se caiga a cero, no que suba.
    check("cubre alguna compra real (±1 min)", res["cobertura_pct"] >= 3.5,
          f'{res["cobertura_pct"]}%')
    check("siempre hay un objetivo", res["sin_objetivo"] == 0, res["sin_objetivo"])
    check("ningún ítem acapara más del 40% de las recomendaciones",
          max(res["reco"].values()) / max(1, sum(res["reco"].values())) <= 0.40,
          sorted(res["reco"].values(), reverse=True)[:1])

    print()
    if _fallos:
        print(f"banco: {len(_fallos)} fallos: {_fallos}")
        return 1
    print("banco: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
