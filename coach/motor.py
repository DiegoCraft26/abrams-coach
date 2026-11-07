"""Motor de decisión: qué comprar, qué vender y si farmear o pelear."""
import json
import os

from .estado import Estado

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache_componentes = None


def mapa_componentes():
    """id de ítem -> ids de los ítems que lo componen (índice de 1,7 KB).

    Lo genera `herramientas/construir_componentes.py` desde data/items.json, que pesa
    2 MB y no se puede cargar en cada lectura sin romper el presupuesto de RAM.
    """
    global _cache_componentes
    if _cache_componentes is None:
        try:
            with open(os.path.join(_RAIZ, "data", "componentes.json"), encoding="utf-8") as f:
                _cache_componentes = json.load(f)
        except Exception:
            _cache_componentes = {}
    return _cache_componentes


def componentes_de(poseidos):
    """Todos los componentes (transitivos) de lo que ya lleva puesto.

    Sirve para no recomendar *Sprint Boots* cuando ya tiene *Shadow Weave*: comprar el
    componente de algo que ya tenés es tirar las almas. Detectado por QA el 2026-11-07.
    """
    mapa = mapa_componentes()
    vistos, pila = set(), [str(x) for x in poseidos]
    while pila:
        actual = pila.pop()
        for componente in mapa.get(actual, ()):
            componente = str(componente)
            if componente not in vistos:
                vistos.add(componente)
                pila.append(componente)
    return vistos

CFG_DEFECTO = {
    "slots": {"weapon": 4, "vitality": 4, "spirit": 4},
    "flex": 0,
    "w_lift": 1.0,
    "w_counter": 0.75,
    "w_fase": 0.40,
    "w_precio": 0.20,
    "w_flujo": 0.50,
    "w_cadena": 1.20,          # lo que suele venir después de lo que ya llevas
    "w_tiempo": 0.18,          # castigo por comprar fuera de su minuto típico
    "w_venta": 1.20,           # coste de tener que vender para hacer sitio
    "lift_minimo": -0.010,       # residual por debajo de esto no se recomienda
    "umbral_ventaja": 0.10,      # 10% de almas sobre la media enemiga
    "fase_minima_s": 600,        # sin recomendaciones de estado antes de 10 min
    "duracion_tipica_s": 2400,
    "venta_minima_tasa": 0.40,
    "venta_margen_pp": 2.0,
    "ventana_fase": 22.0,        # % de partida alrededor del minuto típico de compra   # % de veces que se vende el ítem
    "venta_margen_s": 60,
}


def _cap(estado, cfg):
    s = dict(cfg["slots"])
    if cfg.get("flex"):
        for k in s:
            s[k] += cfg["flex"]
    return s


def economia(estado: Estado):
    """Resumen económico sin comparar líneas ni rivales concretos."""
    mias = estado.yo.almas
    enem = [j.almas for j in estado.enemigos if j.almas is not None]
    aliad = [j.almas for j in estado.aliados if j.almas is not None]
    media_enem = sum(enem)/len(enem) if enem else None
    media_aliad = sum(aliad)/len(aliad) if aliad else None
    delta = (mias - media_enem) if (mias is not None and media_enem is not None) else None
    pct = (delta/media_enem) if (delta is not None and media_enem) else None
    return {"mias": mias, "media_enemiga": media_enem, "media_aliada": media_aliad,
            "delta": delta, "delta_pct": pct}


def estado_tactico(estado: Estado, econ, cfg=CFG_DEFECTO):
    """Devuelve FARM / PELEAR / EQUILIBRIO con un motivo en una línea."""
    if estado.t < cfg["fase_minima_s"]:
        return {"estado": "INICIO", "motivo": "fase inicial: sin recomendación todavía", "objetivo": None}
    p = econ.get("delta_pct")
    if p is None:
        return {"estado": "EQUILIBRIO", "motivo": "no puedo leer las almas del rival", "objetivo": None}
    umbral = cfg["umbral_ventaja"]
    if p <= -umbral:
        falta = int(abs(econ["delta"])*1.1)
        return {"estado": "FARM", "motivo": f"vas {int(abs(p)*100)}% atrás en almas",
                "objetivo": f"farmea hasta +{falta:,} almas para emparejar"}
    if p >= umbral:
        return {"estado": "PELEAR", "motivo": f"vas {int(p*100)}% arriba: presiona",
                "objetivo": "busca pelea y objetivos"}
    return {"estado": "EQUILIBRIO", "motivo": f"diferencia de almas {int(p*100):+d}%: ni atrás ni arriba",
            "objetivo": "sigue el ritmo, no fuerces"}


def _slots_usados(estado, cat):
    usados = {}
    for iid in estado.yo.items:
        d = cat.get(str(iid))
        if d and d["slot"]:
            usados[d["slot"]] = usados.get(d["slot"], 0) + 1
    return usados


def _es_mejora_de(item_id, poseidos, cat):
    """Deadlock no tiene árbol de mejoras: comprar siempre ocupa slot.
    Se deja la función para no romper llamadas, pero siempre es False."""
    return False


def _fase_fit(t_s, min_compra, cfg):
    if not min_compra:
        return 0.5
    t_rel = (t_s / cfg["duracion_tipica_s"]) * 100.0
    return max(0.0, 1.0 - abs(t_rel - min_compra) / 45.0)


def _bonus_counter(item_id, enemigos_heroes, conoc, cfg, indice=None):
    total, cuenta = 0.0, 0
    indice = indice or {}
    for h in enemigos_heroes:
        hid = indice.get(str(h).lower().replace(" ", "_").replace("-", "_"), str(h))
        d = conoc["counters"].get(str(hid), {}).get(str(item_id))
        if d and d.get("delta") is not None:
            peso = min(1.0, (d.get("n") or 0) / 5000.0)   # poca muestra, poco peso
            delta = max(-0.04, min(0.04, d["delta"]))     # techo: evita que un matchup ruidoso domine
            total += delta * peso
            cuenta += 1
    return (total / cuenta) if cuenta else 0.0


def _bonus_cadena(item_id, poseidos, conoc):
    """Probabilidad de que este ítem sea el siguiente, dado lo que ya llevas."""
    sig = (conoc.get("flujo") or {}).get("siguiente") or {}
    mejor = 0.0
    for poseido in poseidos:
        lista = sig.get(str(poseido))
        if not lista:
            continue
        total = sum(x["n"] for x in lista) or 1
        for x in lista:
            if x["id"] == str(item_id):
                mejor = max(mejor, x["n"]/total)
    return mejor


def _bonus_pareja(item_id, poseidos, conoc):
    mejor = 0.0
    for p in conoc["pares"]:
        if str(item_id) in (p["a"], p["b"]):
            otro = p["b"] if p["a"] == str(item_id) else p["a"]
            if otro in poseidos:
                mejor = max(mejor, p["lift"])
    return mejor


def fase_flujo(t_s, conoc):
    """Columna del grafo real de compras, mezclada con la siguiente.

    Antes elegía `col = t // 600` a secas, así que en t=600 el peso de cada ítem saltaba
    de golpe y la recomendación podía cambiar en segundos (violación de la invariante de
    los 10 s, QA 2026-11-07). Ahora el peso de cada ítem se interpola linealmente hacia la
    columna siguiente, de modo que cruzar el minuto 10 ya no cambia nada bruscamente.
    """
    flujo = conoc.get("flujo") or {}
    fases = flujo.get("fases") or {}
    if not fases:
        return None, {}
    intervalo = flujo.get("fase_intervalo_s", 600) or 600
    claves = sorted(fases, key=int)

    def columna(k):
        elegida = claves[0]
        for c in claves:
            if int(c) <= k:
                elegida = c
        return elegida

    posicion = max(0.0, float(t_s)) / float(intervalo)
    objetivo = int(posicion)
    fraccion = posicion - objetivo
    actual = columna(objetivo)
    siguiente = columna(objetivo + 1)
    ahora = {x["id"]: x for x in fases.get(actual, [])}
    luego = ahora if siguiente == actual else {x["id"]: x for x in fases.get(siguiente, [])}
    if not luego:
        return actual, ahora

    neutro = 0.48        # equivalente al -0.02 que se aplica al ítem que no está en fase
    mezcla = {}
    for iid in set(ahora) | set(luego):
        a, b = ahora.get(iid) or {}, luego.get(iid) or {}
        wa = a.get("wr_ajustado", neutro)
        wb = b.get("wr_ajustado", neutro)
        mezcla[iid] = {"id": iid,
                       "wr_ajustado": (1 - fraccion) * wa + fraccion * wb,
                       "n": max(a.get("n") or 0, b.get("n") or 0)}
    return actual, mezcla


def apertura_ids(conoc):
    return {a["id"] for a in (conoc.get("flujo") or {}).get("apertura", [])}


def peso_apertura(t_s, cfg=CFG_DEFECTO):
    """Cuánto sigue pesando "estoy en la apertura". Rampa, nunca un escalón.

    Antes el filtro era `t < 600` a secas: al cruzar exactamente el minuto 10 el conjunto
    de candidatos cambiaba de golpe y el ítem recomendado cambiaba en segundos (violación
    de la invariante de los 10 s, detectada por QA el 2026-11-07). Con una rampa la
    preferencia se apaga de forma continua.
    """
    desde = cfg.get("apertura_desde_s", 480.0)
    hasta = cfg.get("apertura_hasta_s", 720.0)
    if t_s <= desde:
        return 1.0
    if t_s >= hasta:
        return 0.0
    return (hasta - t_s) / (hasta - desde)


def candidatos(estado: Estado, conoc, cat, cfg=CFG_DEFECTO, limite=3):
    econ = economia(estado)
    almas = estado.yo.almas or 0
    poseidos = {str(i) for i in estado.yo.items}
    ya_superados = componentes_de(poseidos)     # componentes de algo que ya tiene
    usados = _slots_usados(estado, cat)
    cap = _cap(estado, cfg)
    heroes_enemigos = [j.heroe for j in estado.enemigos if j.heroe]

    indice = conoc.get("heroes_index", {})
    col, en_fase = fase_flujo(estado.t, conoc)
    apertura = apertura_ids(conoc)
    peso_ap = peso_apertura(estado.t, cfg) if apertura else 0.0
    filas = []
    for iid, d in conoc["items"].items():
        if iid in poseidos:
            continue
        if iid in ya_superados:
            continue
        c = cat.get(iid, {})
        if not c.get("comprable", True):
            continue
        costo = d["costo"] or c.get("costo") or 0
        slot = d["slot"] or c.get("slot")
        if not slot:
            continue
        residual = d["lift_residual"]
        if residual < cfg["lift_minimo"]:
            continue
        # En la apertura sólo se abre con ítems de apertura reales, pero la restricción
        # se apaga en rampa en vez de cortarse en el minuto 10 de golpe.
        castigo_apertura = 0.0
        if peso_ap > 0 and iid not in apertura:
            if estado.t < cfg.get("apertura_desde_s", 480.0):
                continue
            castigo_apertura = cfg.get("w_apertura", 6.0) * peso_ap
        # los ítems que aparecen en la fase actual del grafo reciben su ventaja real
        info_fase = en_fase.get(iid)
        bonus_flujo = (info_fase["wr_ajustado"] - 0.5) if info_fase else -0.02
        # penalización por tiempo, suave pero fuerte: un ítem de minuto 80 a los 10 se cae solo
        t_rel = (estado.t / cfg["duracion_tipica_s"]) * 100.0
        mc = d.get("min_compra") if d.get("min_compra") is not None else t_rel
        distancia_t = abs(t_rel - mc)

        mejora = _es_mejora_de(iid, poseidos, cat)
        libre = cap.get(slot, 4) - usados.get(slot, 0)
        requiere_venta = False
        if not mejora and libre <= 0:
            # slot lleno: se permite si hay algo vendible en ese slot (swap)
            vendibles = [i for i in poseidos if (cat.get(i) or {}).get("slot") == slot
                         and conoc["items"].get(i, {}).get("tasa_venta", 0) >= cfg["venta_minima_tasa"]]
            if not vendibles:
                continue
            requiere_venta = True
        if costo > almas:
            continue

        fase = _fase_fit(estado.t, d.get("min_compra"), cfg)
        counter = _bonus_counter(iid, heroes_enemigos, conoc, cfg, indice)
        pareja = _bonus_pareja(iid, poseidos, conoc)
        cadena = _bonus_cadena(iid, poseidos, conoc)
        precio = 1.0 - min(1.0, costo / max(1, almas))   # premia no gastarte todo

        # todo en puntos porcentuales para que los pesos sean legibles
        score = (cfg["w_lift"]*residual*100
                 + cfg["w_counter"]*counter*100
                 + cfg["w_fase"]*fase*2.0
                 + cfg["w_precio"]*precio*1.0
                 + pareja*100*0.5
                 + cfg["w_flujo"]*bonus_flujo*10
                 + cfg["w_cadena"]*cadena*10
                 - cfg["w_tiempo"]*distancia_t
                 - castigo_apertura
                 - (cfg["w_venta"] if requiere_venta else 0.0))

        razones = []
        if residual > 0:
            razones.append(f"{residual*100:+.1f}pp mejor de lo esperado para su minuto de compra")
        if counter > 0.01:
            razones.append(f"{counter*100:+.1f}pp en este matchup")
        if pareja > 0.005:
            razones.append(f"combo con lo que ya tienes (+{pareja*100:.1f}pp)")
        if cadena > 0.15:
            razones.append(f"suele ser la compra siguiente ({cadena*100:.0f}% de las veces)")
        if info_fase:
            razones.append(f"se compra en esta fase y gana {info_fase['wr_ajustado']*100:.1f}% "
                           f"(n={info_fase['n']:,})")

        filas.append({"id": iid, "nombre": d["nombre"], "costo": costo, "slot": slot,
                      "score": round(score, 4), "residual": residual, "n": d["n"],
                      "razones": razones, "mejora": mejora,
                      "min_compra": d.get("min_compra"),
                      "fase": info_fase["wr_ajustado"] if info_fase else None,
                      "requiere_venta": requiere_venta,
                      "icono": d.get("icono") or f"/icono/{iid}"})

    filas.sort(key=lambda x: -x["score"])
    return filas[:limite], filas


def sugerir_venta(estado: Estado, conoc, cat, cfg=CFG_DEFECTO):
    """Propone vender solo cuando un slot está lleno y lo que entra es claramente mejor.

    En Deadlock todo ítem se vende por su valor completo, así que la pregunta no es
    "¿puedo?", sino "¿mejoro la decisión?". La regla exige tres cosas a la vez:
      1. el ítem que entra supera al que sale por al menos `venta_margen_pp`
      2. el ítem que sale se vende de verdad en partidas reales (tasa_venta)
      3. ya pasó su minuto típico de venta
    """
    poseidos = {str(i) for i in estado.yo.items}
    usados = _slots_usados(estado, cat)
    cap = _cap(estado, cfg)
    almas = estado.yo.almas or 0
    t_rel = (estado.t / cfg["duracion_tipica_s"]) * 100.0
    indice = conoc.get("heroes_index", {})
    heroes = [j.heroe for j in estado.enemigos if j.heroe]

    for slot, n in usados.items():
        if n < cap.get(slot, 4):
            continue
        en_slot = [i for i in poseidos if (cat.get(i) or {}).get("slot") == slot]
        if not en_slot:
            continue
        # el candidato a salir es el peor del slot que además se venda de verdad
        ordenados = sorted(en_slot, key=lambda i: conoc["items"].get(i, {}).get("lift_residual", -1))
        peor = None
        for cand in ordenados:
            info = conoc["items"].get(cand, {})
            if info.get("tasa_venta", 0) < cfg["venta_minima_tasa"]:
                continue
            if info.get("min_venta") and t_rel < info["min_venta"] - cfg["venta_margen_s"]/60:
                continue
            peor = cand
            break
        if peor is None:
            continue
        info_peor = conoc["items"].get(peor, {})
        residual_peor = info_peor.get("lift_residual", -1)

        mejor = None
        for iid, d in conoc["items"].items():
            if iid in poseidos or d["slot"] != slot:
                continue
            if (d["costo"] or 0) > almas:
                continue
            mejora_pp = (d["lift_residual"] - residual_peor)*100
            if mejora_pp < cfg["venta_margen_pp"]:
                continue
            counter = _bonus_counter(iid, heroes, conoc, cfg, indice)
            valor = mejora_pp + counter*100*cfg["w_counter"]
            if not mejor or valor > mejor[1]:
                mejor = (iid, valor, d, mejora_pp)
        if mejor:
            iid, valor, d, mejora_pp = mejor
            return {"vender": peor, "nombre": info_peor.get("nombre", peor),
                    "comprar": iid, "para": d["nombre"], "ganancia_pp": round(mejora_pp, 2),
                    "se_vende": f"{info_peor.get('tasa_venta',0)*100:.0f}% de las partidas",
                    "motivo": f"{d['nombre']} supera a {info_peor.get('nombre', peor)} "
                              f"por {mejora_pp:+.1f}pp y {info_peor.get('nombre', peor)} "
                              f"se vende en {info_peor.get('tasa_venta',0)*100:.0f}% de las partidas"}
    return None


def recomendar(estado: Estado, conoc, cat, cfg=None):
    cfg = cfg or CFG_DEFECTO
    econ = economia(estado)
    tactico = estado_tactico(estado, econ, cfg)
    top, _ = candidatos(estado, conoc, cat, cfg, limite=3)
    venta = sugerir_venta(estado, conoc, cat, cfg)
    # objetivo: lo mejor que todavía no puedes pagar
    objetivo = None
    almas = estado.yo.almas or 0
    for iid, d in conoc["items"].items():
        if iid in {str(x) for x in estado.yo.items}:
            continue
        c = cat.get(iid) or {}
        if not c.get("comprable", True) or not d.get("slot"):
            continue
        if (d["costo"] or 0) <= almas or d["lift_residual"] < cfg["lift_minimo"]:
            continue
        dist = abs((estado.t/cfg["duracion_tipica_s"])*100 - (d.get("min_compra") or 0))
        if dist > 30:
            continue
        if not objetivo or d["lift_residual"] > objetivo["residual"]:
            objetivo = {"id": iid, "nombre": d["nombre"], "costo": d["costo"],
                        "faltan": (d["costo"] or 0) - almas,
                        "residual": d["lift_residual"], "icono": f"/icono/{iid}"}

    plan = []
    if top:
        sig = (conoc.get("flujo") or {}).get("siguiente", {}).get(top[0]["id"], [])
        plan = [{"id": s["id"], "nombre": s["nombre"], "n": s["n"],
                 "icono": f"/icono/{s['id']}"} for s in sig[:2]]
    enemigos = []
    for j in estado.enemigos:
        if not j.heroe:
            continue
        clave = str(j.heroe).lower().replace(" ", "_").replace("-", "_")
        enemigos.append({"heroe": j.heroe, "icono": f"/icono-heroe/{clave}",
                         "almas": j.almas})
    # Los aliados también salen: el panel mostraba sólo los enemigos y se perdía la
    # comparación de economía con el propio equipo (QA de UI, 2026-11-07).
    aliados = []
    for j in estado.aliados:
        clave = str(j.heroe).lower().replace(" ", "_").replace("-", "_") if j.heroe else None
        aliados.append({"heroe": j.heroe,
                        "icono": f"/icono-heroe/{clave}" if clave else None,
                        "almas": j.almas})
    inventario = []
    for iid in estado.yo.items:
        info = conoc["items"].get(str(iid))
        if not info:
            inventario.append({"id": str(iid), "nombre": str(iid), "valor": None,
                               "icono": f"/icono/{iid}"})
            continue
        inventario.append({"id": str(iid), "nombre": info["nombre"],
                           "valor": round(info["lift_residual"]*100, 2),
                           "slot": info["slot"], "icono": f"/icono/{iid}"})
    return {
        "t": estado.t,
        "estado": tactico,
        "economia": econ,
        "recomendaciones": top,
        "venta": venta,
        "plan": plan,
        "objetivo": objetivo,
        "enemigos": enemigos,
        "aliados": aliados,
        "inventario": inventario,
        "almas": estado.yo.almas,
        "confianza": estado.confianza,
        "notas": estado.notas,
    }
