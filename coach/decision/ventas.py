"""Qué vender y en qué orden: la pieza que faltaba en late game.

Feedback de Diego (2026-11-16): «sigue sin tener una noción de venta… debería poner en
algún color diferente algún ítem de los que pueden ser vendidos en prioridad, sobre todo
en late».

El motor ya sabía vender, pero solo cuando un slot estaba lleno **y** la pieza nueva se
pagaba con el bolsillo. En late, con los 12 slots ocupados y 3 600 almas, el panel decía
«build completo» y no nombraba nada: el jugador se quedaba sin saber qué sacar.

Aquí se responde solo a «¿qué de lo que llevo es lo primero que sale?», con las mismas
medidas que usa el motor para comprar:

- residual (`lift_residual`): el que menos rinde por su coste.
- `tasa_venta`: cuánto se vende de verdad en partidas reales; lo que casi nadie vende no
  se propone (sería una orden que no se ejecuta).
- `min_venta`: su minuto típico de venta, en porcentaje de la partida típica. Antes de
  esa ventana no se marca, aunque sobre.
- slot lleno: sin cuatro piezas en el slot no hay nada que abrir.

`nivel`:
  "ahora"  → slot lleno y (late o camino agotado): es lo primero que sale.
  "luego"  → candidato real, pero todavía no toca venderlo.
"""
from __future__ import annotations

# Minuto (de partida) a partir del cual el build empieza a reciclar slots de verdad.
T_LATE_S = 1080
# Dos por pantalla como máximo: una lista de seis «vende esto» no se lee en partida.
MAX_AHORA = 2
NOMBRE_SLOT = {"weapon": "arma", "vitality": "vitalidad", "spirit": "espíritu"}


def _slot(info):
    return (info or {}).get("slot")


def prioridad(estado, conoc, cfg, camino_agotado=False, limite=6):
    """Lista de vendibles ordenada: primero el que menos aporta al slot.

    No decide compras ni toca el camino; publica `nivel` y `motivo` para que el panel
    pinte el ítem distinto y el jugador sepa qué soltar si necesita el hueco o las almas.
    """
    items = [str(i) for i in (getattr(estado.yo, "items", None) or [])]
    t = float(getattr(estado, "t", 0) or 0)
    duracion = max(1.0, float(cfg.get("duracion_tipica_s") or 2400))
    t_rel = (t / duracion) * 100.0
    minimo_tasa = float(cfg.get("venta_minima_tasa") or 0.0)

    ocupados = {}
    for iid in items:
        slot = _slot(conoc["items"].get(iid))
        if slot:
            ocupados[slot] = ocupados.get(slot, 0) + 1

    filas = []
    for iid in items:
        info = conoc["items"].get(iid) or {}
        slot = info.get("slot")
        residual = info.get("lift_residual")
        if not slot or residual is None:
            continue
        # Sin slot lleno no hace falta abrir nada: un hueco libre no se «vende».
        if ocupados.get(slot, 0) < 4:
            continue
        tasa = float(info.get("tasa_venta") or 0.0)
        if tasa < minimo_tasa:
            continue
        min_venta = info.get("min_venta")
        if min_venta is not None and t_rel < float(min_venta) - 1.0:
            continue
        filas.append({"id": iid, "nombre": info.get("nombre") or iid, "slot": slot,
                      "slot_nombre": NOMBRE_SLOT.get(slot, slot),
                      "pp": round(float(residual) * 100.0, 1),
                      "tasa": round(tasa, 3),
                      "costo": int(info.get("costo") or 0)})

    filas.sort(key=lambda x: (x["pp"], -x["tasa"], -x["costo"]))
    # Uno por slot: dos del mismo slot no se venden juntos, el que entra ocupa uno.
    vistos, unicos = set(), []
    for f in filas:
        if f["slot"] in vistos:
            continue
        vistos.add(f["slot"])
        unicos.append(f)

    ahora = bool(camino_agotado) or t >= T_LATE_S
    for i, f in enumerate(unicos[:limite]):
        if ahora and i < MAX_AHORA:
            f["nivel"] = "ahora"
            f["motivo"] = (f"{f['slot_nombre']} lleno: el más flojo "
                           f"({f['pp']:+.1f}pp, se vende en {f['tasa'] * 100:.0f}% "
                           f"de las partidas)")
        else:
            f["nivel"] = "luego"
            f["motivo"] = (f"candidato del slot de {f['slot_nombre']} "
                           f"({f['pp']:+.1f}pp)")
    return unicos[:limite]


def anotar(inventario, ventas):
    """Marca cada ítem del inventario publicado con su prioridad de venta."""
    por_id = {str(v.get("id")): v for v in (ventas or [])}
    for x in inventario or []:
        v = por_id.get(str(x.get("id")))
        if v:
            x["vende"] = v["nivel"]
            x["vende_pp"] = v["pp"]
            x["vende_motivo"] = v["motivo"]
    return inventario
