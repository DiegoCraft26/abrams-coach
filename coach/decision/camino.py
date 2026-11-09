"""Camino de build: apertura → core → spike, con estado explícito.

Por qué existe: el motor puntuaba ítems sueltos y, con pocas almas, el único que cabía
era otro ítem de 800. En una partida normal eso daba 4-5 compras de 800 en los primeros
10 minutos, cuando lo habitual es abrir con 2-3 y empezar a guardar para el core.

Aquí el build es una **secuencia**: tres aperturas, tres piezas de core y los spikes.
La recomendación es siempre el siguiente paso del camino —no el ítem más barato que
quepa— y el estado dice qué hacer con él:

  COMPRAR   lo pagas ahora (o pagas un componente suyo, que siempre se compra).
  AHORRAR   no alcanza: te faltan N almas y, a tu ritmo, son E segundos.
  VENDER    el slot está lleno y conviene vender antes de comprar.

`modo` distingue el ahorro normal (`ahorro`), el rush a un ítem caro (`rush`) y el
farmeo cuando el ETA es largo (`farm`). Los umbrales están en CFG_DEFECTO.
"""
from __future__ import annotations

from . import patrones

CFG_CAMINO = {
    "aperturas": 3,             # cuántos 800 de apertura antes de guardar
    "core": 3,                  # piezas de core (1,600–3,200)
    "max_pasos": 9,
    "ahorro_faltan": 1600,      # ahorra si faltan como mucho esto…
    "ahorro_eta_s": 90,         # …y el ETA no pasa de aquí
    "rush_costo": 3200,         # un ítem caro se persigue si…
    "rush_eta_s": 150,          # …el ETA no pasa de aquí
    "eta_min_tasa": 4.0,        # almas/s mínimas para no dividir por casi cero
}

_CACHE = {"clave": None, "camino": []}


def _componentes(ids):
    """Import perezoso: motor importa este módulo y no puede haber ciclo al cargar."""
    from ..motor import componentes_de
    return componentes_de(ids)


def _costo(conoc, iid):
    return (conoc["items"].get(str(iid)) or {}).get("costo") or 0


def _slot(conoc, cat, iid):
    info = conoc["items"].get(str(iid)) or {}
    return info.get("slot") or (cat.get(str(iid)) or {}).get("slot")


def _etapa(costo):
    if costo <= 800:
        return "apertura"
    if costo <= 3200:
        return "core"
    return "spike"


def _base(conoc, heroe):
    items = conoc.get("items") or {}
    salida = []
    for iid in (heroe.apertura if heroe is not None and heroe.apertura else []):
        iid = str(iid)
        if iid in items and iid not in salida:
            salida.append(iid)
    if len(salida) < 3:
        for a in (conoc.get("flujo") or {}).get("apertura", []):
            iid = str(a["id"])
            if iid in items and iid not in salida:
                salida.append(iid)
            if len(salida) >= 3:
                break
    return salida[:3]


def construir(conoc, cat, heroe=None, max_pasos=None):
    """Camino ordenado de ítems. Se cachea por héroe y tamaño del conocimiento."""
    cfg = CFG_CAMINO
    max_pasos = max_pasos or cfg["max_pasos"]
    clave = (getattr(heroe, "datos", {}).get("clave") if heroe is not None else None,
             len(conoc.get("items") or {}))
    if _CACHE["clave"] == clave and _CACHE["camino"]:
        return [dict(p) for p in _CACHE["camino"]]

    items = conoc.get("items") or {}
    sig = (conoc.get("flujo") or {}).get("siguiente") or {}
    camino = _base(conoc, heroe)
    etapa = {iid: _etapa(_costo(conoc, iid)) for iid in camino}

    while len(camino) < max_pasos:
        core = sum(1 for iid in camino
                   if 800 < _costo(conoc, iid) <= cfg["rush_costo"])
        quiere_core = core < cfg["core"]
        candidatos = []
        for origen in camino:
            for arista in sig.get(origen, []):
                iid = str(arista.get("id"))
                if iid in camino or iid not in items:
                    continue
                if not (cat.get(iid) or {}).get("comprable", True):
                    continue
                # Componente de algo que ya está en el camino: se absorbería y no
                # aporta un paso propio.
                if any(iid in _componentes([p]) for p in camino):
                    continue
                costo = _costo(conoc, iid)
                if quiere_core and not (800 < costo <= cfg["rush_costo"]):
                    continue
                if not quiere_core and costo < cfg["rush_costo"]:
                    continue
                slot = _slot(conoc, cat, iid)
                if slot and sum(1 for p in camino if _slot(conoc, cat, p) == slot) >= 4:
                    continue
                candidatos.append((arista.get("n") or 0, costo, iid))
        if not candidatos:
            # Si el grafo no ofrece una pieza de la etapa que toca, se acepta la
            # siguiente mejor de cualquier etapa antes que cortar el camino.
            for origen in camino:
                for arista in sig.get(origen, []):
                    iid = str(arista.get("id"))
                    if iid in camino or iid not in items:
                        continue
                    if not (cat.get(iid) or {}).get("comprable", True):
                        continue
                    if any(iid in _componentes([p]) for p in camino):
                        continue
                    candidatos.append((arista.get("n") or 0, _costo(conoc, iid), iid))
        if not candidatos:
            break
        # Más frecuente primero; a igualdad, el más barato (llega antes).
        _, _, elegido = max(candidatos, key=lambda c: (c[0], -c[1]))
        camino.append(elegido)
        etapa[elegido] = _etapa(_costo(conoc, elegido))

    salida = [{"id": iid, "nombre": (items.get(iid) or {}).get("nombre", iid),
               "costo": _costo(conoc, iid), "slot": _slot(conoc, cat, iid),
               "etapa": etapa.get(iid, _etapa(_costo(conoc, iid))),
               "icono": f"/icono/{iid}"} for iid in camino]
    _CACHE.update({"clave": clave, "camino": salida})
    return [dict(p) for p in salida]


def _bolsillo(estado, conoc):
    """Lo que puedes gastar ya.

    Si la fuente trae oro sin gastar, ese manda. Si no (replay, OCR), se estima como
    patrimonio menos lo que costó el inventario: el patrimonio incluye lo ya gastado y
    usarlo tal cual hacía que el motor "pudiera" comprar cosas que no puede pagar.
    """
    oro = getattr(estado.yo, "oro", None)
    if oro is not None:
        return max(0, int(oro))
    almas = estado.yo.almas or 0
    gastado = sum(_costo(conoc, i) for i in estado.yo.items)
    return max(0, int(almas - gastado))


def _costo_efectivo(conoc, cat, iid, poseidos):
    info = conoc["items"].get(str(iid)) or {}
    lista = info.get("costo") or (cat.get(str(iid)) or {}).get("costo") or 0
    ahorro = sum(_costo(conoc, x) for x in _componentes([str(iid)]) & poseidos)
    return max(0, lista - ahorro), ahorro, lista


def tasa_almas(conoc, heroe, t_s):
    """Almas por segundo a las que va el build en este momento (benchmark)."""
    tasa = (patrones.benchmark_almas(t_s + 60, heroe)
            - patrones.benchmark_almas(t_s, heroe)) / 60.0
    return max(CFG_CAMINO["eta_min_tasa"], tasa)


def _siguiente(conoc, cat, camino, poseidos, superados):
    for p in camino:
        if str(p["id"]) in poseidos or str(p["id"]) in superados:
            continue
        return p
    return None


def decidir(estado, conoc, cat, cfg=None, heroe=None, venta=None):
    """Estado de la compra: COMPRAR / AHORRAR / VENDER, con ETA y camino."""
    cfg = {**CFG_CAMINO, **(cfg or {})}
    camino = construir(conoc, cat, heroe)
    poseidos = {str(i) for i in estado.yo.items}
    superados = _componentes(poseidos)
    objetivo = _siguiente(conoc, cat, camino, poseidos, superados)
    if objetivo is None:
        return {"accion": "COMPRAR", "modo": "completo", "item": None,
                "objetivo": None, "faltan": 0, "eta_s": 0, "bolsillo": _bolsillo(estado, conoc),
                "motivo": "build completo: no queda nada del camino",
                "camino": [], "alternativas": []}

    bolsillo = _bolsillo(estado, conoc)
    costo, ahorro, lista = _costo_efectivo(conoc, cat, objetivo["id"], poseidos)
    faltan = max(0, costo - bolsillo)
    eta = int(-(-faltan // max(1.0, tasa_almas(conoc, heroe, estado.t))))

    def ficha(iid, nombre, costo_i, ahorro_i=0, lista_i=None):
        return {"id": str(iid), "nombre": nombre, "costo": int(costo_i),
                "costo_lista": int(lista_i if lista_i is not None else costo_i),
                "ahorro": int(ahorro_i), "icono": f"/icono/{iid}"}

    # 1) Componente del objetivo: se compra siempre que se pueda pagar. Es avance
    #    real (se absorbe al subir) y no consume slot extra.
    comprables = []
    for comp in _componentes([objetivo["id"]]):
        if comp in poseidos or comp in superados:
            continue
        if not (cat.get(comp) or {}).get("comprable", True):
            continue
        c_comp, _, _ = _costo_efectivo(conoc, cat, comp, poseidos)
        if c_comp <= bolsillo:
            info = conoc["items"].get(comp) or {}
            comprables.append((info.get("lift_residual") or 0, comp, c_comp, info))
    if comprables:
        _, comp, c_comp, info = max(comprables, key=lambda x: (x[0], -x[2]))
        return {"accion": "COMPRAR", "modo": "componente", "bolsillo": bolsillo,
                "item": ficha(comp, info.get("nombre", comp), c_comp),
                "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo,
                                  ahorro, lista),
                "faltan": 0, "eta_s": 0,
                "motivo": (f"componente de {objetivo['nombre']}: se absorbe al "
                           f"comprarlo y pagas {c_comp:,} ahora"),
                "camino": _tiles(camino, poseidos, superados, objetivo["id"]),
                "alternativas": []}

    # 2) Slot lleno: se vende antes de comprar.
    slot = _slot(conoc, cat, objetivo["id"])
    usados = sum(1 for i in poseidos
                 if _slot(conoc, cat, i) == slot)
    if venta and slot and usados >= 4 and costo <= bolsillo:
        pieza = venta.get("se_vende") or venta.get("para")
        return {"accion": "VENDER", "modo": "slot", "bolsillo": bolsillo,
                "item": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
                "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo,
                                  ahorro, lista),
                "faltan": faltan, "eta_s": eta,
                "motivo": (f"slot {slot} lleno: vende {pieza} y compra "
                           f"{objetivo['nombre']}"),
                "camino": _tiles(camino, poseidos, superados, objetivo["id"]),
                "alternativas": []}

    # 3) ¿Alcanza?
    if costo <= bolsillo:
        return {"accion": "COMPRAR", "modo": "objetivo", "bolsillo": bolsillo,
                "item": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
                "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo,
                                  ahorro, lista),
                "faltan": 0, "eta_s": 0,
                "motivo": (f"siguiente paso del camino ({objetivo['etapa']})"
                           + (f"; pagas {costo:,} con lo que ya llevas" if ahorro else "")),
                "camino": _tiles(camino, poseidos, superados, objetivo["id"]),
                "alternativas": []}

    # 4) Ahorrar / rush / farmear.
    if faltan <= cfg["ahorro_faltan"] and eta <= cfg["ahorro_eta_s"]:
        modo, etiqueta = "ahorro", "AHORRAR"
        motivo = f"faltan {faltan:,} almas; a tu ritmo son {eta} s"
    elif lista >= cfg["rush_costo"] and eta <= cfg["rush_eta_s"]:
        modo, etiqueta = "rush", "AHORRAR"
        motivo = (f"rush a {objetivo['nombre']} ({lista:,}): faltan {faltan:,} "
                  f"y llegas en {eta} s")
    else:
        modo, etiqueta = "farm", "AHORRAR"
        motivo = (f"farmea {faltan:,} almas para {objetivo['nombre']} "
                  f"(ETA {eta} s); no gastes en un 800 suelto")
    return {"accion": etiqueta, "modo": modo, "bolsillo": bolsillo,
            "item": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
            "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
            "faltan": faltan, "eta_s": eta, "motivo": motivo,
            "camino": _tiles(camino, poseidos, superados, objetivo["id"]),
            "alternativas": []}


def _tiles(camino, poseidos, superados, objetivo_id):
    """Los siguientes 5 pasos, con su estado, para la tira del panel."""
    salida = []
    for p in camino:
        iid = str(p["id"])
        if len(salida) >= 5:
            break
        if iid in poseidos or iid in superados:
            estado = "tienes"
        elif iid == str(objetivo_id):
            estado = "ahora"
        else:
            estado = "despues"
        salida.append({**p, "estado": estado})
    return salida
