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
    # Bonus de categoría de Deadlock: 4,800 almas invertidas en arma/vitalidad/espíritu.
    # No se persigue a ciegas (eso vuelve el build genérico); solo se avisa cuando el
    # paso que toca ya está cerca del umbral.
    "bonus_categoria_s": 4800,
    "bonus_aviso_s": 1000,
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


def _elegible(conoc, p, t, permitir_apertura=True):
    """¿Tiene sentido comprar este paso a estas alturas de la partida?

    Antes el camino era fijo y, si el jugador se saltaba la apertura, a los 30 minutos
    seguía recomendando Restorative Shot. Aquí se descarta lo que ya pasó de su ventana:
    - después de 10 min no se compran más 800 de apertura;
    - después de 20 min no se compran piezas de 1,600 salvo que sean componente;
    - si su `min_compra` quedó más de 10 min atrás, se saltó el momento.
    """
    costo = p.get("costo") or 0
    if costo <= 800 and not permitir_apertura:
        return False
    if t >= 1200 and costo < 1600:
        return False
    mc = (conoc["items"].get(str(p["id"])) or {}).get("min_compra")
    if mc:
        min_s = mc / 100.0 * 2400.0
        if t > min_s + 600:
            return False
    return True


def _mejoras(conoc, cat, poseidos, superados, t):
    """Upgrades directos de lo que ya llevas, con su popularidad en el grafo."""
    from ..motor import mapa_componentes
    reversa = {}
    for item, comps in mapa_componentes().items():
        for comp in comps:
            reversa.setdefault(str(comp), []).append(str(item))
    sig = (conoc.get("flujo") or {}).get("siguiente") or {}
    salida = []
    for propio in poseidos:
        base = _costo(conoc, propio)
        for up in reversa.get(propio, []):
            if up in poseidos or up in superados:
                continue
            if not (cat.get(up) or {}).get("comprable", True):
                continue
            info = conoc["items"].get(up)
            if not info:
                continue
            costo = info.get("costo") or 0
            # Un upgrade de 6,400 sobre un 800 no es "completar el ítem", es abrir otra
            # rama: eso lo decide el camino, no el inventario.
            if base and costo > max(2 * base, base + 1600):
                continue
            if t < 600 and costo > 1600:
                continue
            if t < 1200 and costo > 3200:
                continue
            n = next((e.get("n") or 0 for e in sig.get(propio, [])
                      if str(e.get("id")) == up), 0)
            salida.append((n, -costo, {
                "id": up, "nombre": info.get("nombre", up), "costo": costo,
                "slot": info.get("slot") or cat.get(up, {}).get("slot"),
                "etapa": _etapa(costo), "icono": f"/icono/{up}"}))
    salida.sort(reverse=True, key=lambda x: (x[0], x[1]))
    return salida


def _hueco(conoc, cat, poseidos, iid):
    """¿Cabe en su slot? (4 por categoría; los componentes se absorben)."""
    slot = _slot(conoc, cat, iid)
    if not slot:
        return False
    return sum(1 for i in poseidos if _slot(conoc, cat, i) == slot) < 4


def _objetivo(conoc, cat, camino, poseidos, superados, t, contra=None):
    """Siguiente compra: counter fuerte, upgrade de lo que llevas, o camino por fase."""
    mejoras = _mejoras(conoc, cat, poseidos, superados, t)
    # La apertura dura mientras no lleves las tres piezas y no pases del minuto 12.
    # Así no hay un escalón exacto en el 600 que cambie la compra entre dos lecturas
    # separadas por 5 s, y a los 30 min no vuelve a pedir un 800.
    aperturas = sum(1 for p in camino
                    if (p.get("costo") or 0) <= 800 and str(p["id"]) in poseidos)
    permitir_apertura = t < 720 and aperturas < 3
    camino_elegible = [p for p in camino
                       if str(p["id"]) not in poseidos
                       and str(p["id"]) not in superados
                       and _elegible(conoc, p, t, permitir_apertura)]

    # 1) Counter de composición: si hay 2-3 enemigos que lo justifican y el ítem cae
    #    en la fase actual, entra como paso del camino. Es la rama que cambia según
    #    contra quién juegas, no un adorno del ranking.
    elegido_contra = None
    # En los primeros minutos manda la apertura: no se guarda para un counter de 1,600
    # con dos 800 sin comprar. A partir de ahí, la composición sí puede desviar la rama.
    if len(poseidos) < 2 and t < 480:
        contra = {}
    for iid, datos in sorted((contra or {}).items(),
                             key=lambda kv: -float(kv[1].get("puntos") or 0)):
        if float(datos.get("puntos") or 0) < 2.5:
            continue
        if str(iid) in poseidos or str(iid) in superados:
            continue
        info = conoc["items"].get(str(iid))
        if not info or not (cat.get(str(iid)) or {}).get("comprable", True):
            continue
        ficha = {"id": str(iid), "nombre": info.get("nombre", iid),
                 "costo": info.get("costo") or 0,
                 "slot": info.get("slot") or cat.get(str(iid), {}).get("slot"),
                 "etapa": _etapa(info.get("costo") or 0),
                 "icono": f"/icono/{iid}"}
        if not _elegible(conoc, ficha, t, permitir_apertura) or not _hueco(conoc, cat, poseidos, iid):
            continue
        if t < 600 and ficha["costo"] > 1600:
            continue
        if t < 1200 and ficha["costo"] > 3200:
            continue
        ficha["contra"] = datos.get("razon") or "counter de su composición"
        elegido_contra = ficha
        break

    # 2) Upgrade directo de lo que ya llevas: completar lo que pagaste rinde más que
    #    abrir otra rama (era el caso de Slowing Bullets sin subir).
    if elegido_contra:
        candidato = elegido_contra
    elif mejoras:
        candidato = mejoras[0][2]
    elif camino_elegible:
        candidato = camino_elegible[0]
    else:
        # Último recurso: algo del camino que no sea apertura tardía.
        candidato = next((p for p in camino
                          if str(p["id"]) not in poseidos
                          and str(p["id"]) not in superados
                          and (permitir_apertura or (p.get("costo") or 0) > 800)), None)
    if candidato is None:
        return None

    # Determinista: el objetivo depende solo de este estado (reloj en bloques de
    # 10 s, inventario, oro y enemigos). Sin memoria entre llamadas no hay rebotes
    # raros ni decisiones que dependan de lo que se consultó antes.
    return candidato


def decidir(estado, conoc, cat, cfg=None, heroe=None, venta=None, contra=None):
    """Estado de la compra: COMPRAR / AHORRAR / VENDER, con ETA y camino."""
    cfg = {**CFG_CAMINO, **(cfg or {})}
    camino = construir(conoc, cat, heroe)
    poseidos = {str(i) for i in estado.yo.items}
    superados = _componentes(poseidos)
    # Mismo bloque de 10 s que el resto del motor: dos lecturas del mismo momento
    # tienen que dar exactamente la misma compra.
    t_ef = (int(max(0.0, float(estado.t))) // 10) * 10
    objetivo = _objetivo(conoc, cat, camino, poseidos, superados, t_ef,
                         contra=contra)
    if objetivo is None:
        return {"accion": "COMPRAR", "modo": "completo", "item": None,
                "objetivo": None, "faltan": 0, "eta_s": 0, "bolsillo": _bolsillo(estado, conoc),
                "motivo": "build completo: no queda nada del camino",
                "camino": [], "alternativas": []}

    bolsillo = _bolsillo(estado, conoc)
    sufijo = f" · {objetivo['contra']}" if objetivo.get("contra") else ""
    # Aviso de bonus de categoría: informativo, no cambia el camino.
    umbral = cfg["bonus_categoria_s"]
    slot_obj = objetivo.get("slot")
    if slot_obj:
        gastado = sum(_costo(conoc, i) for i in poseidos
                      if _slot(conoc, cat, i) == slot_obj)
        falta_bonus = umbral - gastado
        if 0 < falta_bonus <= cfg["bonus_aviso_s"]:
            sufijo += f" · a {falta_bonus:,} del bonus de {slot_obj}"
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
                           f"comprarlo y pagas {c_comp:,} ahora" + sufijo),
                "camino": _tiles(camino, poseidos, superados, objetivo),
                "alternativas": []}

    # 2) Slot lleno: se vende antes de comprar.
    slot = _slot(conoc, cat, objetivo["id"])
    usados = sum(1 for i in poseidos
                 if _slot(conoc, cat, i) == slot)
    if venta and slot and usados >= 4 and costo <= bolsillo:
        pieza = venta.get("nombre") or venta.get("vender") or "ese ítem"
        return {"accion": "VENDER", "modo": "slot", "bolsillo": bolsillo,
                "item": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
                "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo,
                                  ahorro, lista),
                "faltan": faltan, "eta_s": eta,
                "motivo": (f"slot {slot} lleno: vende {pieza} y compra "
                           f"{objetivo['nombre']}" + sufijo),
                "camino": _tiles(camino, poseidos, superados, objetivo),
                "alternativas": []}

    # 3) ¿Alcanza?
    if costo <= bolsillo:
        return {"accion": "COMPRAR", "modo": "objetivo", "bolsillo": bolsillo,
                "item": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
                "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo,
                                  ahorro, lista),
                "faltan": 0, "eta_s": 0,
                "motivo": (f"siguiente paso del camino ({objetivo['etapa']})"
                           + (f"; pagas {costo:,} con lo que ya llevas" if ahorro else "")
                           + sufijo),
                "camino": _tiles(camino, poseidos, superados, objetivo),
                "alternativas": []}

    # 4) Ahorrar / rush / farmear.
    if faltan <= cfg["ahorro_faltan"] and eta <= cfg["ahorro_eta_s"]:
        modo, etiqueta = "ahorro", "AHORRAR"
        motivo = f"faltan {faltan:,} almas; a tu ritmo son {eta} s" + sufijo
    elif lista >= cfg["rush_costo"] and eta <= cfg["rush_eta_s"]:
        modo, etiqueta = "rush", "AHORRAR"
        motivo = (f"rush a {objetivo['nombre']} ({lista:,}): faltan {faltan:,} "
                  f"y llegas en {eta} s" + sufijo)
    else:
        modo, etiqueta = "farm", "AHORRAR"
        motivo = (f"farmea {faltan:,} almas para {objetivo['nombre']} "
                  f"(ETA {eta} s); no gastes en un 800 suelto" + sufijo)
    return {"accion": etiqueta, "modo": modo, "bolsillo": bolsillo,
            "item": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
            "objetivo": ficha(objetivo["id"], objetivo["nombre"], costo, ahorro, lista),
            "faltan": faltan, "eta_s": eta, "motivo": motivo,
            "camino": _tiles(camino, poseidos, superados, objetivo),
            "alternativas": []}


def _tiles(camino, poseidos, superados, objetivo):
    """Los siguientes 5 pasos, con su estado, para la tira del panel."""
    oid = str(objetivo["id"])
    idx = next((i for i, p in enumerate(camino) if str(p["id"]) == oid), None)
    if idx is not None:
        secuencia = camino[idx:idx + 5]
    else:
        # El objetivo es un upgrade que no está en el camino fijo (p. ej. el de
        # Slowing Bullets): se pone delante y detrás van los siguientes pasos.
        resto = [p for p in camino
                 if str(p["id"]) not in poseidos
                 and str(p["id"]) not in superados
                 and str(p["id"]) != oid]
        secuencia = [objetivo] + resto[:4]
    salida = []
    for p in secuencia:
        iid = str(p["id"])
        if iid in poseidos or iid in superados:
            estado = "tienes"
        elif iid == oid:
            estado = "ahora"
        else:
            estado = "despues"
        salida.append({**p, "estado": estado})
    return salida
