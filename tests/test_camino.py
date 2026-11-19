"""Camino de build: apertura → core → spike y estados COMPRAR/AHORRAR/VENDER."""
import os

import pytest
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from _datos import falta  # noqa: E402

pytestmark = pytest.mark.skipif(
    bool(falta("data/items.json")),
    reason="requiere data/items.json (se regenera con herramientas/datos/mineria.py), no versionado")
sys.path.insert(0, RAIZ)

from coach.decision import camino, heroe as heroes  # noqa: E402
from coach.estado import Estado  # noqa: E402
from coach.motor_api import Motor  # noqa: E402


def _estado(t, almas, items, oro=None, enemigos=None):
    yo = {"heroe": "Abrams", "almas": almas, "items": items}
    if oro is not None:
        yo["oro"] = oro
    return {"t": t, "yo": yo,
            "enemigos": [{"heroe": h, "almas": almas} for h in (enemigos or [])],
            "aliados": [], "fuente": "manual"}


def main():
    m = Motor()
    h = heroes.cargar("abrams")
    ruta = camino.construir(m.conoc, m.cat, h)
    fallos = 0

    def check(nombre, cond, detalle=""):
        nonlocal fallos
        print(f"  {'ok  ' if cond else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")
        if not cond:
            fallos += 1

    print("camino")
    check("trae al menos 8 pasos", len(ruta) >= 8, str(len(ruta)))
    check("no hay repetidos", len({p["id"] for p in ruta}) == len(ruta))
    aperturas = [p for p in ruta if p["etapa"] == "apertura"]
    # Dos y no tres: con 20 500 partidas, 800+800+800 gana 51.2 % (n 12 321) contra
    # 53.3 % de 800+800+1 600 (n 3 201). Ver informes/lab/ENSAYOS-2026-11-17.md.
    check("dos aperturas de 800", len(aperturas) == 2
          and all(p["costo"] == 800 for p in aperturas),
          str([(p["nombre"], p["costo"]) for p in aperturas]))
    check("hay core de 1,600–3,200",
          any(800 < p["costo"] <= 3200 for p in ruta))
    check("hay spike de 3,200+", any(p["costo"] >= 3200 for p in ruta))
    por_slot = {}
    for p in ruta:
        por_slot[p["slot"]] = por_slot.get(p["slot"], 0) + 1
    check("ningún slot pasa de 4", all(v <= 4 for v in por_slot.values()),
          str(por_slot))

    ids = [p["id"] for p in ruta]

    print("decisiones")
    r = m.analizar_dict(_estado(300, 800, []))
    check("con 800 y nada comprado: COMPRAR la apertura",
          r["decision"]["accion"] == "COMPRAR"
          and r["decision"]["item"]["costo"] == 800,
          r["decision"]["item"]["nombre"])

    # Con la apertura cerrada ya no se recomienda otro 800: toca juntar 1,600 y el
    # panel debe decir cuánto falta.
    almas = sum(p["costo"] for p in ruta[:2]) + 800
    r = m.analizar_dict(_estado(300, almas, ids[:2]))
    d = r["decision"]
    check("con la apertura cerrada: el objetivo ya no es un 800",
          d["item"]["costo"] > 800, f'{d["item"]["nombre"]} ({d["item"]["costo"]})')
    check("faltan ≤1,600 y ETA ≤90 s: AHORRAR",
          d["accion"] == "AHORRAR" and d["modo"] == "ahorro"
          and d["faltan"] <= 1600 and d["eta_s"] <= 90,
          f'faltan {d["faltan"]}, eta {d["eta_s"]}, modo {d["modo"]}')

    # Un hueco grande (spike) con ETA larga se llama farmear, no comprar.
    r = m.analizar_dict(_estado(900, sum(p["costo"] for p in ruta[:6]), ids[:6]))
    d = r["decision"]
    check("sin oro para el siguiente: AHORRAR/farm con ETA",
          d["accion"] == "AHORRAR" and d["eta_s"] > 0, d["modo"])

    # Componente del objetivo: se compra siempre que alcance, aunque el objetivo no.
    elegido = None
    for i, p in enumerate(ruta):
        comps = [c for c in camino._componentes([p["id"]])
                 if c not in ids[:i] and (m.cat.get(c) or {}).get("comprable", True)]
        if comps and i > 0:
            elegido = (i, p, comps)
            break
    check("hay un objetivo con componente en el camino", elegido is not None)
    if elegido:
        i, p, comps = elegido
        poseidos = ids[:i]
        costo_comp = min((m.conoc["items"].get(c) or {}).get("costo") or 0
                         for c in comps)
        almas = sum((m.conoc["items"].get(x) or {}).get("costo") or 0 for x in poseidos)
        r = m.analizar_dict(_estado(1200, almas + costo_comp, poseidos))
        d = r["decision"]
        check("el componente del objetivo se compra",
              d["accion"] == "COMPRAR" and d["modo"] == "componente",
              f'{d["item"]["nombre"]} de {p["nombre"]}')

    # Comprar adelantado: no se vuelve a pedir lo anterior del camino.
    r = m.analizar_dict(_estado(1200, 20000, [ids[4]]))
    d = r["decision"]
    antes = {p["nombre"] for p in ruta[:4]}
    check("comprar adelantado salta los pasos previos",
          (d.get("item") or {}).get("nombre") not in antes,
          str((d.get("item") or {}).get("nombre")))

    # Rama por composición: dos móviles justifican antimovilidad y, desde el 2026-11-18,
    # el counter entra **en el camino** (una sola línea en el panel). Antes vivía en una
    # caja aparte que enseñaba Spellbreaker (6 400) al minuto 0 mientras el camino no lo
    # pedía hasta el 25: dos consejos que se contradecían.
    ids_por_nombre = {d.get("nombre"): k for k, d in m.conoc["items"].items()}
    cid = ids_por_nombre["Slowing Bullets"]
    ruta_contra = camino.construir(m.conoc, m.cat, h,
                                   contra_datos={cid: {"puntos": 3.0,
                                                       "razon": "antimovilidad"}})
    nombres = [p["nombre"] for p in ruta_contra]
    check("el counter de composición entra en el camino", "Slowing Bullets" in nombres)
    pos = nombres.index("Slowing Bullets") if "Slowing Bullets" in nombres else -1
    check("y entra después de la apertura", pos >= 2, str(pos))
    check("marcado como counter para la tira",
          any(p.get("contra") and p["nombre"] == "Slowing Bullets" for p in ruta_contra))
    check("un solo counter por camino", sum(1 for p in ruta_contra if p.get("contra")) <= 1)
    check("sin composición el camino no lleva counter",
          not any(p.get("contra") for p in camino.construir(m.conoc, m.cat, h)))
    check("un 6 400 de composición no entra sin que el rival vaya arriba",
          "Spellbreaker" not in [p["nombre"] for p in camino.construir(
              m.conoc, m.cat, h,
              contra_datos={ids_por_nombre["Spellbreaker"]: {"puntos": 4.0,
                                                             "razon": "x"}})])
    # La tira ya no promete pasos que el motor no va a pedir: a los 25 min un 800 de
    # apertura sin comprar sale del camino. Era el "Restorative Shot de cuarto ítem".
    tarde = camino.construir(m.conoc, m.cat, h, t=1500, poseidos=())
    check("a los 25 min la tira no lleva apertura sin comprar",
          all((p.get("costo") or 0) > 800 for p in tarde))
    r_comp = m.analizar_dict(_estado(900, 6000, [], enemigos=["haze", "seven", "lash"]))
    contra_lista = [c["nombre"] for c in (r_comp.get("contra_composicion") or [])]
    check("el motor sigue publicando la composición para el visor",
          "Slowing Bullets" in contra_lista, str(contra_lista))
    check("el bonus de categoría se publica a 4,800",
          r.get("categorias", {}).get("weapon", {}).get("umbral") == 4800
          and "falta" in r.get("categorias", {}).get("weapon", {}),
          str(r.get("categorias")))
    check("los slots se publican con sus huecos",
          r.get("slots", {}).get("weapon", {}).get("total") == 4
          and "libres" in r.get("slots", {}).get("weapon", {}),
          str(r.get("slots")))

    # Vender cuando el slot del objetivo está lleno: se consulta el decisor con una
    # venta disponible para no depender de que `sugerir_venta` la encuentre.
    objetivo = ruta[3]
    llenos = [iid for iid, d in m.cat.items()
              if d.get("slot") == objetivo["slot"] and iid not in ids][:4]
    est = Estado.desde_dict(_estado(900, 12000, ids[:3] + llenos))
    d = camino.decidir(est, m.conoc, m.cat, heroe=h, venta={"se_vende": "algo"})
    check("slot lleno y venta disponible: VENDER", d["accion"] == "VENDER",
          f'{d["accion"]} · {d.get("motivo")}')

    print()
    if fallos:
        print(f"camino: {fallos} fallos")
        return 1
    print("camino: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
