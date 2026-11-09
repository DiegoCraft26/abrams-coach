"""Camino de build: apertura → core → spike y estados COMPRAR/AHORRAR/VENDER."""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    check("tres aperturas de 800", len(aperturas) == 3
          and all(p["costo"] == 800 for p in aperturas))
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

    # Con las tres aperturas puestas ya no se recomienda otro 800: toca juntar
    # 1,600 y el panel debe decir cuánto falta.
    almas = sum(p["costo"] for p in ruta[:3]) + 800
    r = m.analizar_dict(_estado(300, almas, ids[:3]))
    d = r["decision"]
    check("con las 3 aperturas: el objetivo ya no es un 800",
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

    # Rama por composición: dos móviles justifican antimovilidad; sin enemigos no.
    r = m.analizar_dict(_estado(900, 6000, [], enemigos=["haze", "seven", "lash"]))
    d = r["decision"]
    check("con dos móviles la rama es antimovilidad",
          (d.get("item") or {}).get("nombre") == "Slowing Bullets"
          and "slow con balas" in (d.get("motivo") or ""),
          str((d.get("item") or {}).get("nombre")))
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
