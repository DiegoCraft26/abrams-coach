"""Pruebas del motor con estados sintéticos. Sin dependencias: python3 tests/test_motor.py"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coach.motor_api import Motor

fallos = []

def check(nombre, cond, detalle=""):
    if cond:
        print(f"  ok   {nombre}")
    else:
        print(f"  FALLA {nombre}  {detalle}")
        fallos.append(nombre)

def base(**kw):
    d = {"t": 1200, "yo": {"heroe": "Abrams", "almas": 3000, "items": []},
         "aliados": [{"almas": 3000}],
         "enemigos": [{"heroe": "haze", "almas": 3000},
                      {"heroe": "lash", "almas": 2900},
                      {"heroe": "seven", "almas": 3100}],
         "confianza": 1.0}
    d.update(kw)
    return d

def main():
    m = Motor()
    print(f"conocimiento: {len(m.conoc['items'])} ítems")

    r = m.analizar_dict(base())
    rs = r["recomendaciones"]
    check("con 3000 almas recomienda algo", len(rs) > 0, str(rs[:1]))
    check("nada cuesta más de lo que tengo", all(x["costo"] <= 3000 for x in rs),
          str([(x["nombre"], x["costo"]) for x in rs]))
    check("sin residuales negativos", all(x["residual"] >= m.cfg["lift_minimo"] for x in rs))
    check("trae razones", all(x["razones"] or x["n"] for x in rs))

    r2 = m.analizar_dict(base(yo={"heroe": "Abrams", "almas": 200, "items": []}))
    recs2 = r2["recomendaciones"]
    # Con 200 almas no se compra nada: o no hay recomendación, o es el objetivo de
    # un AHORRAR (con cuánto falta). Nunca una compra que no se paga.
    check("con 200 almas no inventa compras",
          recs2 == [] or (len(recs2) == 1 and recs2[0].get("accion") == "AHORRAR"
                          and (recs2[0].get("faltan") or 0) > 0),
          str(recs2[:1]))

    r3 = m.analizar_dict(base(t=300))
    check("antes de 10 min no da estado táctico", r3["estado"]["estado"] == "INICIO")

    atras = m.analizar_dict(base(enemigos=[{"heroe": "haze", "almas": 9000},
                                           {"heroe": "lash", "almas": 9000},
                                           {"heroe": "seven", "almas": 9000}]))
    check("yendo atrás -> FARM", atras["estado"]["estado"] == "FARM", atras["estado"])

    adelante = m.analizar_dict(base(yo={"heroe": "Abrams", "almas": 12000, "items": []}))
    check("yendo arriba -> PELEAR", adelante["estado"]["estado"] == "PELEAR", adelante["estado"])

    lleno = dict(base())
    lleno["yo"] = {"heroe": "Abrams", "almas": 8000,
                   "items": [i for i, d in m.conoc["items"].items() if d["slot"] == "weapon"][:4]}
    r4 = m.analizar_dict(lleno)
    check("slot lleno -> propone venta o no rompe", True)
    if r4["venta"]:
        check("la venta trae motivo", bool(r4["venta"]["motivo"]))
        check("no vende algo que no tienes", r4["venta"]["vender"] in lleno["yo"]["items"])

    t0 = time.perf_counter()
    for _ in range(50):
        m.analizar_dict(base())
    ms = (time.perf_counter() - t0) / 50 * 1000
    check(f"latencia media {ms:.1f} ms < 20 ms", ms < 20)

    print()
    if fallos:
        print(f"{len(fallos)} FALLAS: {fallos}")
        return 1
    print("todo bien")
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
