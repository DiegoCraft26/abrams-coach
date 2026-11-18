"""Amenazas, perfil de build y counters: lo que hace que el build no sea siempre el mismo.

Tres cosas que se comprueban aquí y que antes no existían:
  1. un enemigo muy por encima de tu equipo se marca y se dice que no se busca solo;
  2. ese rival desvía la compra hacia el counter que lo frena;
  3. el camino cambia con la economía (yendo atrás se acorta, yendo arriba se adelanta)
     sin dejar de ser determinista: el mismo estado da la misma decisión.

Sin dependencias: `python3 tests/test_amenazas.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.decision import camino, heroe as heroes, perfil as perfil_mod  # noqa: E402
from coach.estado import Estado  # noqa: E402
from coach.motor_api import Motor  # noqa: E402


def _estado(t=1500, almas=27000, items=None, enemigos=None, aliados=None):
    return {
        "t": t,
        "yo": {"heroe": "Abrams", "almas": almas, "items": items or []},
        "aliados": aliados if aliados is not None else [
            {"heroe": "Kelvin", "almas": 26000},
            {"heroe": "Haze", "almas": 25000},
            {"heroe": "Dynamo", "almas": 28000},
        ],
        "enemigos": enemigos if enemigos is not None else [
            {"heroe": "Haze", "almas": 40000, "bajas": 9, "muertes": 2},
            {"heroe": "Lash", "almas": 26000, "bajas": 3, "muertes": 5},
            {"heroe": "Seven", "almas": 27000, "bajas": 4, "muertes": 4},
            {"heroe": "Pocket", "almas": 25000, "bajas": 2, "muertes": 6},
            {"heroe": "Ivy", "almas": 19000, "bajas": 1, "muertes": 5},
        ],
        "confianza": 1.0,
    }


def main():
    m = Motor()
    h = heroes.cargar("abrams")
    fallos = 0

    def check(nombre, cond, detalle=""):
        nonlocal fallos
        print(f"  {'ok  ' if cond else 'FALLA'} {nombre}"
              f"{(' · ' + str(detalle)) if detalle else ''}")
        if not cond:
            fallos += 1

    print("amenazas")
    r = m.analizar_dict(_estado())
    am = r["amenazas"]
    check("la media es la de tu equipo, no la enemiga",
          am["media_equipo"] == 26500, am["media_equipo"])
    peor = am["peor"] or {}
    check("Haze con 40k contra 26.5k es crítico",
          peor.get("heroe") == "Haze" and peor.get("nivel") == "critico",
          f'{peor.get("heroe")} {peor.get("nivel")}')
    check("crítico = no buscarlo solo", peor.get("evitar_solo") is True)
    check("la alerta nombra al rival y su ventaja",
          "Haze" in (am["alerta"] or "") and "%" in (am["alerta"] or ""),
          am["alerta"])
    check("el que va parejo no se marca",
          not next((e for e in am["lista"] if e["heroe"] == "Lash"), {}).get("evitar_solo"))
    check("el que va por debajo se marca como flojo",
          next((e for e in am["lista"] if e["heroe"] == "Ivy"), {}).get("nivel") == "flojo")

    r_parejo = m.analizar_dict(_estado(enemigos=[
        {"heroe": "Haze", "almas": 27000}, {"heroe": "Lash", "almas": 26000}]))
    check("partida pareja: sin alerta", r_parejo["amenazas"]["alerta"] is None)

    r_sin_equipo = m.analizar_dict(_estado(aliados=[]))
    check("sin aliados no se inventa la amenaza",
          r_sin_equipo["amenazas"]["referencia"] == "media de tu equipo"
          or r_sin_equipo["amenazas"]["media_equipo"] is not None)

    print("perfil")
    e = Estado.desde_dict(_estado())
    am_lista = am["lista"]
    # Sin rival crítico: yendo atrás manda la economía, no un counter.
    atras = perfil_mod.calcular(e, {"delta_pct": -0.22},
                                 [{"heroe": "Lash", "nivel": "parejo"}], t_ef=1500)
    check("yendo atrás el perfil acorta el camino",
          atras["modo"] == "atras" and atras["tope"] <= 3200, atras["motivo"])
    arriba = perfil_mod.calcular(e, {"delta_pct": 0.25},
                                 [{"heroe": "Ivy", "nivel": "flojo"}], t_ef=1500)
    check("yendo arriba el perfil adelanta el spike",
          arriba["modo"] == "arriba" and arriba["tope"] > 4800, arriba["motivo"])
    contra = perfil_mod.calcular(e, {"delta_pct": 0.0}, am_lista, t_ef=1500)
    check("con un crítico el perfil es su counter",
          contra["modo"] == "contra" and contra["rival"] == "Haze"
          and len(contra["contra"]) > 0, contra["contra"])

    print("camino")
    camino._CACHE = {"clave": None, "caminos": {}}
    ruta_base = camino.construir(m.conoc, m.cat, h)
    camino._CACHE = {"clave": None, "caminos": {}}
    ruta_atras = camino.construir(m.conoc, m.cat, h, perfil=atras)
    camino._CACHE = {"clave": None, "caminos": {}}
    ruta_arriba = camino.construir(m.conoc, m.cat, h, perfil=arriba)
    camino._CACHE = {"clave": None, "caminos": {}}
    ruta_contra = camino.construir(m.conoc, m.cat, h, perfil=contra)
    # La apertura son dos piezas (no tres): a partir de ahí el perfil puede desviar.
    check("el inicio es el mismo en los tres perfiles",
          [p["id"] for p in ruta_base[:2]] == [p["id"] for p in ruta_atras[:2]]
          == [p["id"] for p in ruta_contra[:2]])
    check("el camino cambia con el perfil",
          [p["id"] for p in ruta_base] != [p["id"] for p in ruta_arriba],
          str([p["nombre"] for p in ruta_arriba]))
    check("el counter del crítico entra en el camino",
          any(p["id"] in contra["contra"] for p in ruta_contra),
          str([p["nombre"] for p in ruta_contra[:5]]))
    check("el camino sigue sin repetidos ni slots imposibles",
          len({p["id"] for p in ruta_contra}) == len(ruta_contra)
          and all(sum(1 for x in ruta_contra if x["slot"] == s) <= 4
                  for s in ("weapon", "vitality", "spirit")))

    print("decisión")
    d = m.analizar_dict(_estado())
    check("el counter del rival que va arriba manda",
          "counter" in (d["decision"].get("motivo") or "").lower()
          or "Haze" in (d["decision"].get("motivo") or ""),
          d["decision"].get("motivo"))
    check("el perfil se publica para el panel",
          d["perfil"]["modo"] == "contra" and d["perfil"]["rival"] == "Haze")
    check("los enemigos salen marcados",
          any(e.get("evitar_solo") for e in d["enemigos"])
          and all("nivel" in e for e in d["enemigos"]))
    check("el counter urgente aparece en la lista aparte",
          any(c.get("urgente") for c in d["contra_composicion"]),
          str([(c["nombre"], c["contra_quien"]) for c in d["contra_composicion"]]))

    # Determinismo: la misma consulta dos veces (y un segundo después) da lo mismo.
    a = m.analizar_dict(_estado(t=1500))
    b = m.analizar_dict(_estado(t=1500))
    c = m.analizar_dict(_estado(t=1503))
    firma = lambda x: (x["decision"]["item"]["id"], x["decision"]["accion"],
                       tuple(p["id"] for p in x["camino"]))
    check("misma consulta, misma compra y mismo camino", firma(a) == firma(b))
    check("3 s después sigue igual (bloque de 10 s)", firma(a) == firma(c))

    print()
    if fallos:
        print(f"amenazas: {fallos} fallos")
        return 1
    print("amenazas: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
