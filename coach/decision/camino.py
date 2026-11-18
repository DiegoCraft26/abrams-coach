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

import os

from . import patrones

CFG_CAMINO = {
    # Dos, no tres: medido en 20 500 partidas, la apertura 800+800+800 gana 51.2 %
    # (n 12 321) contra 53.3 % de 800+800+1 600 (n 3 201) y 54.5 % de 800+1 600+3 200
    # (n 1 622). Ver informes/lab/ENSAYOS-2026-11-17.md.
    "aperturas": 2,             # cuántos 800 de apertura antes de guardar
    # Ventana en la que no se compran 800 nuevos (segundos de partida). Medido en
    # informes/lab/ENSAYOS-2026-11-17.md: entre el minuto 10 y el 30 un 800 rinde
    # −2.3 y −2.9 ΔW por 1 000 almas. `None` la desactiva (comportamiento viejo).
    "sin_800_desde_s": 600,
    "sin_800_hasta_s": 1800,
    # Puntuar los candidatos del camino con ΔW medido en partidas reales
    # (data/dw_items.json) en vez de sólo con la frecuencia del grafo.
    "usar_dw": True,
    # Pesos de la puntuación del camino. Configurables para poder medirlos sin tocar
    # el código; los valores por defecto son los que estaban escritos a mano.
    "w_freq": 0.30, "w_econ": 0.25, "w_bal": 0.10, "w_dw": 0.35,
    # Refuerzo de los ítems que rinden con el equipo 2k o más abajo (R3).
    "usar_dw_atras": False, "w_atras": 0.20,
    "core": 3,                  # piezas de core (1,600–3,200)
    "max_pasos": 12,
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
    # Ítems forzados a propósito para un A/B (variable ABRAMS_FORZAR, ids separados por
    # comas). Vacío en producción: solo lo usa `herramientas/evaluar_motor.py` para
    # medir una hipótesis antes de decidir si entra al build.
    "forzar_items": [],
}

# A/B: ABRAMS_FORZAR="id1,id2" mete esos ítems al camino para medir una hipótesis.
# Vacío en producción (nadie define la variable).
CFG_CAMINO["forzar_items"] = [x.strip() for x in
                              (os.environ.get("ABRAMS_FORZAR") or "").split(",") if x.strip()]

_CACHE = {"clave": None, "caminos": {}}
_DW = {"ruta": None, "datos": {}}


def _dw_atras():
    """ΔW por ítem medido en partidas donde el equipo iba 2k o más abajo.

    Lo genera `herramientas/lab/r3_deficit.py --json data/dw_atras.json` sobre 18 828
    partidas, condicionado por déficit de equipo. Va aparte del ΔW general a propósito:
    un ítem puede rendir sólo cuando vas atrás.
    """
    import json
    import os
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "dw_atras.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return (json.load(f) or {}).get("items") or {}
    except (OSError, ValueError):
        return {}


def _dw_items():
    """ΔW por ítem medido en partidas reales (`data/dw_items.json`).

    Lo genera `herramientas/lab/exportar_dw.py` con 20 500 partidas del parche. Si el
    archivo no está, el término no entra y el motor se comporta como antes.
    """
    import json
    import os
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "dw_items.json")
    if _DW["ruta"] == ruta:
        return _DW["datos"]
    _DW["ruta"] = ruta
    try:
        with open(ruta, encoding="utf-8") as f:
            _DW["datos"] = (json.load(f) or {}).get("items") or {}
    except (OSError, ValueError):
        _DW["datos"] = {}
    return _DW["datos"]


def _componentes(ids):
    """Import perezoso: motor importa este módulo y no puede haber ciclo al cargar."""
    from ..motor import componentes_de
    return componentes_de(ids)


def _costo(conoc, iid):
    return (conoc["items"].get(str(iid)) or {}).get("costo") or 0


def _ya_hay_800(camino, conoc, cfg):
    """¿El camino ya lleva las piezas de 800 que permite la apertura?"""
    return sum(1 for p in camino if _costo(conoc, p) <= 800) >= int(cfg["aperturas"])


def _slot(conoc, cat, iid):
    info = conoc["items"].get(str(iid)) or {}
    return info.get("slot") or (cat.get(str(iid)) or {}).get("slot")


def _min_compra(conoc, iid):
    return (conoc["items"].get(str(iid)) or {}).get("min_compra")


def _etapa(costo):
    if costo <= 800:
        return "apertura"
    if costo <= 3200:
        return "core"
    return "spike"


_META = {"ruta": None, "datos": None}


def meta_observado():
    """Apertura observada en partidas reales (`data/meta_abrams.json`).

    La guía de `data/heroes/abrams.json` decía Restorative Shot; las 626 partidas del
    cache dicen Extra Regen y Spirit Strike. Manda lo medido; si el archivo no está, se
    sigue usando la guía.
    """
    import json
    import os
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "meta_abrams.json")
    if _META["ruta"] == ruta:
        return _META["datos"] or {}
    _META["ruta"] = ruta
    try:
        with open(ruta, encoding="utf-8") as f:
            _META["datos"] = json.load(f)
    except (OSError, ValueError):
        _META["datos"] = {}
    return _META["datos"] or {}


def _base(conoc, heroe, cfg=None):
    items = conoc.get("items") or {}
    salida = []
    # 1) meta observado en partidas reales
    for iid in (meta_observado().get("apertura") or []):
        iid = str(iid)
        if iid in items and iid not in salida:
            salida.append(iid)
    # 2) apertura de la guía del héroe
    for iid in (heroe.apertura if heroe is not None and heroe.apertura else []):
        iid = str(iid)
        if iid in items and iid not in salida:
            salida.append(iid)
    # 3) apertura del grafo de compras
    if len(salida) < 3:
        for a in (conoc.get("flujo") or {}).get("apertura", []):
            iid = str(a["id"])
            if iid in items and iid not in salida:
                salida.append(iid)
            if len(salida) >= 3:
                break
    cfg = cfg or CFG_CAMINO
    return salida[:max(1, int(cfg.get("aperturas", 3)))]


def _elegir(candidatos, perfil, camino, conoc, cat, cfg=None):
    """Elige el siguiente paso mezclando frecuencia real y perfil.

    Antes ganaba siempre la arista más frecuente del grafo (`n`), y el perfil no movía
    nada: por eso el camino era idéntico en todas las partidas. La frecuencia se
    normaliza contra el máximo del propio conjunto y pesa 0.60; el perfil (economía y
    balance de slots) pesa 0.40. Un counter del rival que va arriba gana directamente.
    """
    cfg = cfg or CFG_CAMINO
    dw = _dw_items() if cfg.get("usar_dw") else {}
    contra = {str(x) for x in (perfil.get("contra") or ())}
    modo = perfil.get("modo")
    atras = _dw_atras() if (cfg.get("usar_dw_atras") and modo == "atras") else {}
    tope = max(1, int(perfil.get("tope") or 1))
    max_n = max((c[0] or 0) for c in candidatos) or 1
    mejor, mejor_punto = None, None
    for arista_n, costo, iid, slot in candidatos:
        if str(iid) in contra:
            punto = 10.0
        else:
            frecuencia = (arista_n or 0) / max_n
            economia = 0.5
            if modo == "atras":
                economia = max(0.0, 1.0 - costo / tope)
            elif modo == "arriba":
                economia = min(1.0, costo / tope)
            en_slot = (sum(1 for p in camino if _slot(conoc, cat, p) == slot)
                       if slot else 0)
            balance = max(0.0, 1.0 - en_slot / 3.0)
            if dw:
                # ΔW normalizado a [0,1]: lo que el ítem gana por encima de su estado,
                # medido en partidas reales. Sustituye parte del peso de la frecuencia,
                # que sólo dice qué se compra mucho.
                d = dw.get(str(iid)) or {}
                dw_n = (float(d.get("norm", 0.0)) + 1) / 2
                if atras:
                    a = atras.get(str(iid)) or {}
                    punto_atras = (float(a.get("norm", 0.0)) + 1) / 2
                    punto = (float(cfg.get("w_freq", 0.45)) * frecuencia
                         + float(cfg.get("w_econ", 0.25)) * economia
                         + float(cfg.get("w_bal", 0.10)) * balance
                             + float(cfg.get("w_dw", 0.20)) * dw_n
                             + float(cfg.get("w_atras", 0.20)) * punto_atras)
                else:
                    punto = (float(cfg.get("w_freq", 0.45)) * frecuencia
                             + float(cfg.get("w_econ", 0.25)) * economia
                             + float(cfg.get("w_bal", 0.10)) * balance
                             + float(cfg.get("w_dw", 0.20)) * dw_n)
            else:
                punto = (float(cfg.get("w_freq", 0.30)) * frecuencia
                         + float(cfg.get("w_econ", 0.25)) * economia
                         + float(cfg.get("w_bal", 0.10)) * balance)
        if mejor_punto is None or punto > mejor_punto + 1e-9:
            mejor, mejor_punto = (arista_n, costo, iid, slot), punto
        elif abs(punto - mejor_punto) <= 1e-9 and mejor is not None and costo < mejor[1]:
            # Empate exacto: el más barato llega antes.
            mejor = (arista_n, costo, iid, slot)
    return mejor


def construir(conoc, cat, heroe=None, max_pasos=None, perfil=None, cfg=None):
    """Camino ordenado de ítems. Se cachea por héroe, conocimiento, perfil y reglas.

    `cfg` entra desde `_decidir`: antes se leía CFG_CAMINO del módulo y un A/B por
    configuración no cambiaba el camino, sólo la decisión final.
    """
    cfg = {**CFG_CAMINO, **(cfg or {})}
    max_pasos = max_pasos or cfg["max_pasos"]
    perfil = perfil or {}
    # La clave incluye las reglas que cambian la forma del camino: sin esto, un A/B
    # en el mismo proceso devolvía el camino cacheado de la configuración anterior
    # (y los tests se contaminaban entre sí).
    clave = (getattr(heroe, "datos", {}).get("clave") if heroe is not None else None,
             len(conoc.get("items") or {}),
             perfil.get("clave") or "base",
             # El tope de precio cambia con la fase y cambia el camino: sin él en la
             # clave, un camino construido a los 25 min (tope 6 400) se reusaba a los
             # 8 min y recomendaba Phantom Strike antes de tiempo.
             perfil.get("tope"),
             tuple(sorted(cfg.get("forzar_items") or ())),
             int(cfg.get("aperturas", 3)),
             cfg.get("sin_800_desde_s"),
             cfg.get("sin_800_hasta_s"))
    if _CACHE["clave"] == clave and _CACHE["caminos"].get(clave):
        return [dict(p) for p in _CACHE["caminos"][clave]]

    tope = perfil.get("tope")
    items = conoc.get("items") or {}
    sig = (conoc.get("flujo") or {}).get("siguiente") or {}
    camino = _base(conoc, heroe, cfg)
    contra = {str(x) for x in (perfil.get("contra") or ())}
    forzados = {str(x) for x in (cfg.get("forzar_items") or ()) if str(x) in items}
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
                # El camino no lleva más 800 de los que permite la apertura: si no,
                # el relleno y el fallback volvían a colar un tercero (Extra Health
                # aparecía como «apertura» número tres).
                if costo <= 800 and sum(1 for p in camino
                                        if _costo(conoc, p) <= 800) >= int(cfg["aperturas"]):
                    continue
                if quiere_core and not (800 < costo <= cfg["rush_costo"]):
                    continue
                if not quiere_core and costo < cfg["rush_costo"]:
                    continue
                if tope and costo > tope:
                    continue
                slot = _slot(conoc, cat, iid)
                if slot and sum(1 for p in camino if _slot(conoc, cat, p) == slot) >= 4:
                    continue
                candidatos.append((arista.get("n") or 0, costo, iid, slot))
        # El counter del rival que va arriba no tiene por qué estar en el grafo del
        # build (nadie compra Tropical Bullets tras Restorative Shot): entra como
        # candidato propio. Uno por camino, para no convertirlo en un build de counters.
        for iid in forzados:
            if iid in camino or iid not in items:
                continue
            if not (cat.get(iid) or {}).get("comprable", True):
                continue
            slot = _slot(conoc, cat, iid)
            if slot and sum(1 for p in camino if _slot(conoc, cat, p) == slot) >= 4:
                continue
            candidatos.append((0, _costo(conoc, iid), iid, slot))
        if contra and not (contra & set(camino)):
            for iid in contra:
                if iid in camino or iid not in items:
                    continue
                if not (cat.get(iid) or {}).get("comprable", True):
                    continue
                if any(iid in _componentes([p]) for p in camino):
                    continue
                costo = _costo(conoc, iid)
                if tope and costo > tope:
                    continue
                slot = _slot(conoc, cat, iid)
                if slot and sum(1 for p in camino if _slot(conoc, cat, p) == slot) >= 4:
                    continue
                candidatos.append((0, costo, iid, slot))
        if not candidatos:
            # Si el grafo no ofrece una pieza de la etapa que toca, se acepta la
            # siguiente mejor de cualquier etapa antes que cortar el camino. El tope de
            # precio y la etapa se relajan aquí: mejor un camino más largo que uno cortado.
            for origen in camino:
                for arista in sig.get(origen, []):
                    iid = str(arista.get("id"))
                    if iid in camino or iid not in items:
                        continue
                    if not (cat.get(iid) or {}).get("comprable", True):
                        continue
                    if any(iid in _componentes([p]) for p in camino):
                        continue
                    if _costo(conoc, iid) <= 800 and _ya_hay_800(camino, conoc, cfg):
                        continue
                    if tope and _costo(conoc, iid) > tope:
                        continue
                    slot = _slot(conoc, cat, iid)
                    if slot and sum(1 for p in camino if _slot(conoc, cat, p) == slot) >= 4:
                        continue
                    candidatos.append((arista.get("n") or 0, _costo(conoc, iid), iid,
                                       slot))
        if not candidatos and tope:
            # Último recurso: se relaja el tope, pero no hasta un 6 400 antes de la
            # fase que lo permite. Antes el relleno colaba Phantom Strike al minuto 8
            # (el banco lo contaba como recomendación imposible).
            for origen in camino:
                for arista in sig.get(origen, []):
                    iid = str(arista.get("id"))
                    if iid in camino or iid not in items:
                        continue
                    if not (cat.get(iid) or {}).get("comprable", True):
                        continue
                    if any(iid in _componentes([p]) for p in camino):
                        continue
                    if _costo(conoc, iid) <= 800 and _ya_hay_800(camino, conoc, cfg):
                        continue
                    # Aquí se relaja el tope, pero no hasta un 6 400 antes de la fase
                    # que lo permite: el relleno colaba Phantom Strike al minuto 8.
                    if _costo(conoc, iid) >= 6400 and (tope or 0) < 6400:
                        continue
                    slot = _slot(conoc, cat, iid)
                    if slot and sum(1 for p in camino if _slot(conoc, cat, p) == slot) >= 4:
                        continue
                    candidatos.append((arista.get("n") or 0, _costo(conoc, iid), iid,
                                       slot))
        if not candidatos:
            break
        # Frecuencia normalizada contra el perfil: el camino cambia con la partida.
        _, _, elegido, _ = _elegir(candidatos, perfil, camino, conoc, cat, cfg)
        camino.append(elegido)
        etapa[elegido] = _etapa(_costo(conoc, elegido))

    # A/B: el ítem forzado entra al final del camino y en el sitio que le toca por su
    # `min_compra` (percentil de partida). Antes se insertaba en el paso 4 y un 6,400
    # salía al minuto 5, que es medir otra cosa.
    for iid in forzados:
        if iid in camino:
            continue
        mc = float(_min_compra(conoc, iid) or 100.0)
        pos = len(camino)
        for i, otro in enumerate(camino):
            if float(_min_compra(conoc, otro) or 100.0) > mc:
                pos = i
                break
        camino.insert(pos, iid)
        etapa[iid] = _etapa(_costo(conoc, iid))
        # Si su slot queda por encima de 4, sale la pieza más floja de ese slot
        # (menor lift residual), sin tocar la apertura ni otros forzados.
        slot_f = _slot(conoc, cat, iid)
        mismo = [x for x in camino if _slot(conoc, cat, x) == slot_f and x not in forzados]
        while len(mismo) + 1 > 4:
            debil = min(mismo, key=lambda x: (conoc["items"].get(str(x)) or {}).get(
                "lift_residual") or 0.0)
            camino.remove(debil)
            mismo.remove(debil)

    # El grafo de compras se queda corto (nadie compra 12 piezas seguidas en el orden
    # exacto): sin esto, la build se declaraba «completa» con 9 ítems y 12 huecos, que es
    # lo que Diego vio al minuto 25. Se completa con lo más rentable que quepa en los
    # slots que quedan, de la fase más avanzada a la más temprana.
    if len(camino) < max_pasos:
        camino.extend(_rellenar(conoc, cat, camino, max_pasos - len(camino), tope))
        for iid in camino:
            etapa.setdefault(iid, _etapa(_costo(conoc, iid)))

    salida = [{"id": iid, "nombre": (items.get(iid) or {}).get("nombre", iid),
               "costo": _costo(conoc, iid), "slot": _slot(conoc, cat, iid),
               "etapa": etapa.get(iid, _etapa(_costo(conoc, iid))),
               "icono": f"/icono/{iid}"} for iid in camino]
    _CACHE.update({"clave": clave, "caminos": {clave: salida}})
    return [dict(p) for p in salida]


def _rellenar(conoc, cat, camino, cuantos, tope):
    """Rellena el final del camino con lo mejor que quepa, sin repetir ni romper slots.

    Orden: fase del flujo de mayor a menor (los ítems de cierre primero) y, a igualdad,
    el que más veces aparece. Es deliberadamente conservador: no inventa ítems, los elige
    del mismo grafo que usa el resto del motor.
    """
    items = conoc.get("items") or {}
    fases = ((conoc.get("flujo") or {}).get("fases") or {})
    candidatos = []
    for clave_fase in sorted(fases, key=lambda x: -int(x)):
        for x in fases[clave_fase]:
            iid = str(x["id"])
            if iid in camino or iid not in items:
                continue
            if not (cat.get(iid) or {}).get("comprable", True):
                continue
            costo = _costo(conoc, iid)
            if costo < 1600:
                continue          # la apertura ya está cubierta por _base
            if tope and costo > tope:
                continue
            candidatos.append((iid, costo))
    salida = []
    for iid, _ in candidatos:
        if len(salida) >= cuantos:
            break
        if iid in salida:
            continue
        slot = _slot(conoc, cat, iid)
        if not slot:
            continue
        ocupados = sum(1 for p in camino + salida if _slot(conoc, cat, p) == slot)
        if ocupados >= 4:
            continue
        if any(iid in _componentes([p]) for p in camino + salida):
            continue
        salida.append(iid)
    return salida


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


def tasa_almas(conoc, heroe, t_s, real=None):
    """Almas por segundo a las que va el build en este momento.

    `real` son las almas/s medidas en ESTA partida (última ventana del historial). Manda
    sobre el benchmark: el ETA del panel tiene que ser «cuánto tardas tú», no «cuánto
    tarda el jugador medio». Si la medida no es creíble (cero, negativa o un salto de
    recompra) se vuelve al benchmark en vez de proyectar con un número raro.
    """
    if real is not None and 0 < real <= 90:
        return max(CFG_CAMINO["eta_min_tasa"], float(real))
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
    # Minuto 22 y no 20: justo en el 20 la regla cambiaba el objetivo al cruzar el
    # borde, que es lo que la invariante 3 prohíbe (dos consultas seguidas dando
    # ítems distintos sin que cambie nada más).
    if t >= 1320 and costo < 1600:
        return False
    # Un tier 4 de 6,400 antes del minuto 15 no es un spike: es medio build en un ítem
    # que no llegas a pagar. El banco de partidas lo vio 72 veces en 48k muestras.
    if costo >= 6400 and t < 900:
        return False
    mc = (conoc["items"].get(str(p["id"])) or {}).get("min_compra")
    if mc:
        min_s = mc / 100.0 * 2400.0
        # Ventana de +15 min en vez de +10: el corte a los 10 creaba un borde por
        # ítem que cambiaba el objetivo sin que cambiara el inventario.
        if t > min_s + 900:
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


def _objetivo(conoc, cat, camino, poseidos, superados, t, contra=None, perfil=None,
              bolsillo=None, cfg=None):
    """Siguiente compra: counter fuerte, upgrade de lo que llevas, o camino por fase."""
    perfil = perfil or {}
    cfg = cfg or CFG_CAMINO
    modo = perfil.get("modo")
    mejoras = _mejoras(conoc, cat, poseidos, superados, t)
    # La apertura dura mientras no lleves las tres piezas y no pases del minuto 12.
    # Así no hay un escalón exacto en el 600 que cambie la compra entre dos lecturas
    # separadas por 5 s, y a los 30 min no vuelve a pedir un 800.
    aperturas = sum(1 for p in camino
                    if (p.get("costo") or 0) <= 800 and str(p["id"]) in poseidos)
    # La apertura se cierra por piezas, no por reloj: el corte a los 12 minutos era
    # otro borde que cambiaba el objetivo sin que cambiara nada en el inventario.
    permitir_apertura = t < 900 and aperturas < int(cfg.get("aperturas", 3))
    # Ventana sin 800: medido con ΔW sobre 20 500 partidas (R4). El reloj, no el
    # inventario, decide cuándo un 800 deja de rendir por oro.
    # El 800 sólo se permite mientras la apertura sigue abierta (las piezas pactadas)
    # o cuando ya pasó la franja medida. Con la apertura cerrada, un 800 "de core" es
    # el cuarto objeto de 800 que el propio Diego detectó como sinsentido.
    hasta_800 = cfg.get("sin_800_hasta_s")
    bloqueo_800 = (hasta_800 is not None and t < hasta_800
                   and not permitir_apertura)
    # Si ya compraste algo que va más adelante en el camino, se salta hasta ahí: no
    # tiene sentido seguir pidiendo los pasos previos. Es lo que pasaba al comprar
    # adelantado un ítem de la línea de tiempo.
    # Solo lo que de verdad tienes adelanta el camino. Antes también adelantaban los
    # componentes de lo que tienes, y comprar un Healing Booster te dejaba con el camino
    # «completo» al minuto 4 (visto en el banco de partidas, match 60142085): el motor
    # creía que ya habías comprado un paso de más adelante solo porque compartía
    # componente. `superados` sigue sirviendo para no recomendar lo que se absorbería.
    indices = [i for i, p in enumerate(camino) if str(p["id"]) in poseidos]
    desde = (max(indices) + 1) if indices else 0
    camino_elegible = [p for i, p in enumerate(camino)
                       if i >= desde
                       and str(p["id"]) not in poseidos
                       and str(p["id"]) not in superados
                       and _elegible(conoc, p, t, permitir_apertura)
                       # Un 800 "suelto" en la franja medida resta almas; el counter
                       # del rival entra por su propia rama y no pasa por aquí.
                       and not (bloqueo_800 and (p.get("costo") or 0) <= 800)]

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
        # El counter del rival que va por encima no espera a la fase ni al tope de
        # precio del perfil: si ese rival está ganando la partida, se frena. El de
        # composición sigue con la ventana y el presupuesto de siempre.
        urgente = bool(datos.get("amenaza"))
        # Ni el counter urgente pide un 6 400 antes del minuto 16: a esa altura el
        # único estado en que cabe es haber saltado todo, y el banco lo cuenta como
        # recomendación imposible.
        if t < 960 and ficha["costo"] > 4800:
            continue
        if not urgente:
            if t < 600 and ficha["costo"] > 1600:
                continue
            if t < 1200 and ficha["costo"] > 3200:
                continue
            # Counter de composición: oportunista y barato (tier 2/3). Un tier 4 de
            # 6,400 solo se compra cuando el rival que lo justifica ya está ganando la
            # partida; si no, se lo come el camino y el build no avanza.
            if ficha["costo"] > 3200:
                continue
            tope = perfil.get("tope")
            if tope and ficha["costo"] > tope:
                continue
            # El counter de composición NO secuestra el build: solo entra si ya es un
            # paso del camino. Slowing Bullets salía como recomendación principal media
            # partida (cualquier composición con dos móviles lo justificaba) y encima
            # oscilaba con el oro: "ahorra para Hunter's Aura" ↔ "compra Slowing
            # Bullets" cada vez que el bolsillo cruzaba 1,600. Ahora el camino manda y el
            # counter sigue en su sección, que para eso está. El del rival que va por
            # encima (urgente) sí entra: eso no es composición, es la partida.
            if str(iid) not in {str(p["id"]) for p in camino}:
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
        # El último recurso también respeta la ventana de compra: sin `_elegible` se
        # colaban tier 4 antes del minuto 15 (el banco lo contó 1,064 veces en el A/B).
        candidato = next((p for i, p in enumerate(camino)
                          if i >= desde
                          and str(p["id"]) not in poseidos
                          and str(p["id"]) not in superados
                          and _elegible(conoc, p, t, permitir_apertura)), None)
    if candidato is None:
        return None

    # Determinista: el objetivo depende solo de este estado (reloj en bloques de
    # 10 s, inventario, oro y enemigos). Sin memoria entre llamadas no hay rebotes
    # raros ni decisiones que dependan de lo que se consultó antes.
    return candidato


def decidir(estado, conoc, cat, cfg=None, heroe=None, venta=None, contra=None,
            perfil=None, tasa=None):
    """Decisión con el perfil ya aplicado y con el perfil publicado en la salida."""
    perfil = perfil or {}
    r = _decidir(estado, conoc, cat, cfg=cfg, heroe=heroe, venta=venta,
                 contra=contra, perfil=perfil, tasa=tasa)
    # `target` es la dirección del build (el ítem final). `item` puede ser su componente
    # cuando ese componente se absorbe: el panel y el visor tienen que poder distinguir
    # "compro el componente de X" de "cambié de objetivo".
    obj = r.get("objetivo") or r.get("item") or {}
    r["target"] = obj.get("id")
    r["target_nombre"] = obj.get("nombre")
    r["perfil"] = perfil.get("etiqueta")
    r["perfil_modo"] = perfil.get("modo")
    r["perfil_motivo"] = perfil.get("motivo")
    r["perfil_contra"] = perfil.get("rival")
    return r


def _decidir(estado, conoc, cat, cfg=None, heroe=None, venta=None, contra=None,
             perfil=None, tasa=None):
    """Estado de la compra: COMPRAR / AHORRAR / VENDER, con ETA y camino."""
    cfg = {**CFG_CAMINO, **(cfg or {})}
    perfil = perfil or {}
    camino = construir(conoc, cat, heroe, perfil=perfil, cfg=cfg)
    poseidos = {str(i) for i in estado.yo.items}
    superados = _componentes(poseidos)
    # Mismo bloque de 10 s que el resto del motor: dos lecturas del mismo momento
    # tienen que dar exactamente la misma compra.
    t_ef = (int(max(0.0, float(estado.t))) // 10) * 10
    bolsillo = _bolsillo(estado, conoc)
    objetivo = _objetivo(conoc, cat, camino, poseidos, superados, t_ef,
                         contra=contra, perfil=perfil, bolsillo=bolsillo, cfg=cfg)
    if objetivo is None:
        return {"accion": "COMPRAR", "modo": "completo", "item": None,
                "objetivo": None, "faltan": 0, "eta_s": 0, "bolsillo": _bolsillo(estado, conoc),
                "motivo": "build completo: no queda nada del camino",
                "camino": [], "alternativas": [], "perfil": perfil.get("etiqueta")}

    sufijo = f" · {objetivo['contra']}" if objetivo.get("contra") else ""
    # El perfil se dice en la misma línea del motivo: si el camino cambió por el rival
    # que va arriba o por ir atrás en almas, el jugador tiene que ver por qué.
    if perfil.get("modo") not in (None, "base") and not objetivo.get("contra"):
        sufijo += f" · {perfil.get('motivo')}"
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
    eta = int(-(-faltan // max(1.0, tasa_almas(conoc, heroe, estado.t, real=tasa))))

    def ficha(iid, nombre, costo_i, ahorro_i=0, lista_i=None):
        return {"id": str(iid), "nombre": nombre, "costo": int(costo_i),
                "costo_lista": int(lista_i if lista_i is not None else costo_i),
                "ahorro": int(ahorro_i), "icono": f"/icono/{iid}"}

    # 1) Componente del objetivo: se compra siempre que se pueda pagar. Es avance
    #    real (se absorbe al subir) y no consume slot extra.
    comprables = []
    # Si el padre ya se paga, no se compra un componente suelto: pagar la mitad y
    # seguir ahorrando retrasa el ítem que decide. La medición de ΔW sobre las partidas
    # de Diego lo dejó claro: pedía Duration Extender mientras él compraba Melee Charge
    # (−14.8 pp de valor esperado).
    for comp in (() if costo <= bolsillo else _componentes([objetivo["id"]])):
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
