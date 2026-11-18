"""Resultado de partida: parser puro, API que no rompe y guardado en la base.

Lo importante aquí no es que funcione con una partida real, sino que **no rompa la app**
cuando la API cambie, tarde o devuelva basura: el parser se prueba con JSON sintético y
`desde_api` con un `urlopen` que falla.
"""
import os
import sys
import tempfile
import urllib.error

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import resultado as R  # noqa: E402
from coach.persistencia.db import conectar, migrar  # noqa: E402
from coach.persistencia.repos import (  # noqa: E402
    Compra,
    Partida,
    Resultado,
    guardar_compra,
    guardar_partida,
    guardar_resultado,
    winrate_por_primer_item,
)

_fallos = []


def check(nombre, cond, detalle=""):
    print(f"  {'ok  ' if cond else 'FALLA'} {nombre}"
          f"{(' · ' + str(detalle)) if detalle else ''}")
    if not cond:
        _fallos.append(nombre)


def metadata(ganador=1, equipo=1, cuenta=555, heroe=6, segundos=2400):
    return {"match_info": {
        "match_id": 42, "duration_s": segundos, "winning_team": ganador,
        "players": [
            {"account_id": 111, "player_slot": 0, "team": 0, "hero_id": 4,
             "kills": 1, "deaths": 2, "assists": 3},
            {"account_id": cuenta, "player_slot": 5, "team": equipo, "hero_id": heroe,
             "kills": 7, "deaths": 2, "assists": 9},
        ],
    }}


def main():
    print("parser")
    r = R.desde_metadata(metadata(ganador=1, equipo=1))
    check("ganada se guarda como 1", r and r["win"] == 1, r)
    check("kda con formato a/b/c", r and r["kda"] == "7/2/9", r)
    check("duración leída", r and r["duracion_s"] == 2400)
    r = R.desde_metadata(metadata(ganador=1, equipo=0))
    check("perdida se guarda como 0", r and r["win"] == 0, r)
    r = R.desde_metadata(metadata(), cuenta=111)
    check("con --cuenta elige ese jugador", r and r["win"] == 0, r)
    r = R.desde_metadata(metadata(), slot=5)
    check("con --slot elige ese jugador", r and r["win"] == 1, r)

    print("casos que NO deben inventar")
    dos = metadata()
    dos["match_info"]["players"].append(
        {"account_id": 777, "player_slot": 9, "team": 0, "hero_id": 6,
         "kills": 0, "deaths": 0, "assists": 0})
    check("dos Abrams sin cuenta ni slot -> None", R.desde_metadata(dos) is None)
    check("sin players -> None", R.desde_metadata({"match_info": {"match_id": 1}}) is None)
    check("sin ganador -> None",
          R.desde_metadata({"match_info": {"players": [{"team": 1, "hero_id": 6}]}}) is None)
    check("JSON que no es dict -> None", R.desde_metadata("basura") is None)
    check("match_info que no es dict -> None", R.desde_metadata({"match_info": 3}) is None)

    print("API caída")
    original = R.urllib.request.urlopen

    def caida(*a, **k):
        raise urllib.error.URLError("sin red")

    R.urllib.request.urlopen = caida
    try:
        check("sin red devuelve None, no lanza", R.desde_api(123) is None)
    finally:
        R.urllib.request.urlopen = original

    print("base de datos")
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "coach.db")
        con = conectar(ruta)
        migrar(con)
        guardar_partida(con, Partida(match_id=42, duracion_s=2400, heroe="Abrams"))
        guardar_compra(con, Compra(match_id=42, ts=10.0, item="Extra Regen",
                                   item_id="2829638276"))
        datos = R.desde_metadata(metadata())
        guardar_resultado(con, Resultado(match_id=42, win=datos["win"],
                                         duracion_s=datos["duracion_s"],
                                         kda=datos["kda"], fuente=datos["fuente"]))
        con.commit()
        fila = con.execute("SELECT win, kda FROM resultados WHERE match_id = 42").fetchone()
        check("resultado guardado en la base", fila and fila[0] == 1, dict(fila or {}))
        filas = winrate_por_primer_item(con)
        check("winrate por primer ítem ya tiene datos",
              filas and filas[0]["item"] == "Extra Regen" and filas[0]["winrate"] == 1.0,
              filas)
        # Idempotente: guardar dos veces no duplica ni revienta.
        guardar_resultado(con, Resultado(match_id=42, win=1))
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM resultados").fetchone()[0]
        check("guardar dos veces no duplica", n == 1, n)
        con.close()

    print()
    if _fallos:
        print(f"resultado: {len(_fallos)} fallos: {_fallos}")
        return 1
    print("resultado: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
