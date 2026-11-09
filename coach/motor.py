"""Motor de decisión: qué comprar, qué vender y si farmear o pelear."""
import json
import os

from .decision import camino as camino_mod
from .decision import explicador, heroe as heroes, patrones, situacionales
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
    propios = {str(x) for x in poseidos}
    vistos, pila = set(), list(propios)
    while pila:
        actual = pila.pop()
        for componente in mapa.get(actual, ()):
            componente = str(componente)
            if componente not in vistos:
                vistos.add(componente)
                pila.append(componente)
    # Un ciclo en el mapa (A compone B y B compone A) hacía que `componentes_de`
    # devolviera el propio ítem; entonces "el componente del objetivo" era el objetivo.
    return vistos - propios

CFG_DEFECTO = {
    "slots": {"weapon": 4, "vitality": 4, "spirit": 4},
    "w_lift": 1.0,
    "w_counter": 0.75,
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
    "venta_margen_s": 60,
    # --- fase económica y power spikes (2026-11-07) ---
    "w_presupuesto": 0.30,       # castigo por gastar más de lo que falta para el hito
    "w_recuperacion": 0.90,      # castigo a ítems caros cuando vas atrás
    "recuperacion_desde": 3200,   # coste a partir del cual cuenta como "caro" yendo atrás
    "contexto_activo": True,     # ganancias por contexto y señales de composición
    "w_balance": 0.45,           # premia rellenar el slot más flojo del build
    # --- scoring por contexto (docs/experto/scoring.md) ---
    "contexto_delta": 1.0,       # tope en puntos de lo que el contexto mueve un score
    "empate_margen": 0.5,        # puntos por debajo de los cuales dos ítems son un empate
    "ctx_lift_cierre": 0.10,     # cuánto baja el peso del residual en el cierre (ver ganancias)
    "w_bonus_categoria": 0.40,   # empujón suave si el ítem cae cerca del bonus de 4,800
}


def _cap(estado, cfg):
    return dict(cfg["slots"])


def economia(estado: Estado):
    """Resumen económico sin comparar líneas ni rivales concretos."""
    mias = estado.yo.almas
    enem = [j.almas for j in estado.enemigos if j.almas is not None]
    media_enem = sum(enem)/len(enem) if enem else None
    delta = (mias - media_enem) if (mias is not None and media_enem is not None) else None
    pct = (delta/media_enem) if (delta is not None and media_enem) else None
    return {"mias": mias, "media_enemiga": media_enem,
            "delta": delta, "delta_pct": pct}


def estado_tactico(estado: Estado, econ, cfg=CFG_DEFECTO):
    """Devuelve FARM / PELEAR / EQUILIBRIO con un motivo en una línea."""
    if estado.t < cfg["fase_minima_s"]:
        # El motivo se enseña al lado de una recomendación real: decir "sin recomendación
# todavía" ahí se contradecía con el "COMPRA AHORA" de arriba (visto en partida).
        return {"estado": "INICIO", "motivo": "fase inicial: build de apertura", "objetivo": None}
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


def _acotar(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


# 1.0 en cada peso = el scoring de siempre. Se usa cuando el contexto está apagado.
GANANCIAS_NEUTRAS = {"lift": 1.0, "counter": 1.0, "precio": 1.0, "cadena": 1.0,
                     "venta": 1.0, "comp": 0.0, "atras": 0.0, "adelante": 0.0,
                     "late": 0.0, "delta_pct": 0.0}


def ganancias_contexto(estado: Estado, econ, heroes_enemigos, cfg=CFG_DEFECTO):
    """Cuánto se multiplica cada peso del scoring en este estado (1.0 = neutro).

    Los pesos eran constantes, así que el score de un ítem era casi una propiedad suya y
    el panel repetía la misma recomendación media partida. Aquí se mueven con cuatro
    señales que ya llegan al motor: fase, almas relativas, composición enemiga y (por el
    descuento de componentes, en `candidatos()`) inventario propio.

    Todas son rampas lineales acotadas a [0.60, 1.40]: cruzar 25 %, 45 % o 10 pp de
    déficit no produce ningún salto, y el reloj ya viene en bloques de 10 s, así que dos
    lecturas del mismo momento dan exactamente el mismo número (invariante de los 10 s).
    Los números y su medición están en docs/experto/scoring.md; aquí sólo se aplican.
    """
    # Mismo bloque de 10 s que usa el resto del motor: sin esto, dos consultas separadas
    # por 4 s caen a lados distintos de la rampa y la recomendación cambia (QA 2026-11-07).
    t = (int(max(0.0, float(estado.t))) // 10) * 10.0
    fase_pct = t / cfg["duracion_tipica_s"] * 100.0
    early = _acotar(1 - (fase_pct - 25) / 25)     # 1 hasta el 25 %, 0 desde el 50 %
    late = _acotar((fase_pct - 45) / 25)          # 0 hasta el 45 %, 1 desde el 70 %
    d = econ.get("delta_pct") or 0.0
    atras = _acotar(-d / 0.10)                    # 0 parejo o arriba · 1 yendo 10 % atrás
    adelante = _acotar(d / 0.10)
    senales = situacionales.señales_composicion(heroes_enemigos)
    comp = _acotar(max(senales.values()) / 3.0) if senales else 0.0

    return {
        # El promedio de 1.9 M de partidas describe a otro jugador: pesa menos cuando la
        # composición está cargada, cuando vas atrás y en el cierre (mismo argumento que
        # `cadena`: el build ya está hecho y la media describe a quien todavía lo arma), y
        # algo más cuando vas arriba.
        "lift": _acotar(1.25 - 0.35*comp - 0.25*atras + 0.10*adelante
                        - cfg.get("ctx_lift_cierre", 0.20)*late, 0.60, 1.40),
        # El matchup decide la línea en los primeros minutos: sube con composición y early.
        "counter": _acotar(0.70 + 0.45*comp + 0.15*early, 0.60, 1.40),
        # Yendo atrás cada alma pesa; yendo arriba gastarla es lo correcto.
        "precio": _acotar(0.95 + 0.45*atras - 0.25*adelante, 0.60, 1.40),
        # El grafo del build dice mucho temprano y poco en el cierre, cuando ya está hecho.
        "cadena": _acotar(1.25 - 0.25*late - 0.20*atras + 0.15*adelante, 0.60, 1.40),
        # En el cierre los slots están llenos y vender cuesta más.
        "venta": _acotar(0.75 + 0.50*late, 0.60, 1.40),
        "comp": comp, "atras": atras, "adelante": adelante, "late": late, "delta_pct": d,
    }


def motivo_ganancia(gan):
    """Por qué el coeficiente no es el global, en una línea (None si no se movió)."""
    if not gan:
        return None
    partes = []
    d = gan.get("delta_pct") or 0.0
    if gan.get("atras"):
        partes.append(f"vas {abs(int(d*100))}% atrás en almas")
    elif gan.get("adelante"):
        partes.append(f"vas {int(d*100)}% arriba en almas")
    if gan.get("comp"):
        partes.append(f"{int(round(gan['comp']*3))} enemigo(s) con esa amenaza")
    if gan.get("late"):
        partes.append("a esta altura la media de partidas pesa menos")
    if not partes:
        return None
    return "coeficiente ajustado ×{:.2f}: {}".format(gan["lift"], " y ".join(partes))


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


def apertura_ids(conoc, heroe=None):
    """Ítems de apertura: primero los del héroe, si no los de la base general."""
    if heroe is not None and heroe.apertura:
        return set(heroe.apertura)
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


def candidatos(estado: Estado, conoc, cat, cfg=CFG_DEFECTO, limite=3, heroe=None):
    econ = economia(estado)
    almas = estado.yo.almas or 0
    poseidos = {str(i) for i in estado.yo.items}
    ya_superados = componentes_de(poseidos)     # componentes de algo que ya tiene
    usados = _slots_usados(estado, cat)
    gastado = {}
    for iid in poseidos:
        slot_i = (conoc["items"].get(iid) or {}).get("slot") or (cat.get(iid) or {}).get("slot")
        if slot_i:
            gastado[slot_i] = gastado.get(slot_i, 0) + (
                (conoc["items"].get(iid) or {}).get("costo") or 0)
    cap = _cap(estado, cfg)
    heroes_enemigos = [j.heroe for j in estado.enemigos if j.heroe]

    indice = conoc.get("heroes_index", {})
    # Todas las señales que dependen del reloj se calculan en bloques de 10 s. Sin esto,
    # dos consultas separadas por 4 s caían a lados distintos de la rampa de apertura y
    # el ítem recomendado cambiaba (invariante 3 del QA, 2026-11-07). Con el bloque de
    # 10 s, "casi el mismo momento" da exactamente la misma recomendación.
    t_efectivo = (int(max(0.0, float(estado.t))) // 10) * 10.0
    col, en_fase = fase_flujo(t_efectivo, conoc)
    apertura = apertura_ids(conoc, heroe)
    peso_ap = peso_apertura(t_efectivo, cfg) if apertura else 0.0

    # --- contexto de fase económica (power spikes del build de Abrams) ---
    hito = patrones.hito_siguiente(almas, heroe)
    faltan_fase = (hito - almas) if hito else 0
    pct_vs_enemigos = econ.get("delta_pct")
    atras = (pct_vs_enemigos is not None and pct_vs_enemigos <= -cfg["umbral_ventaja"])
    # Señal de composición: la heurística solo puntúa si los datos de matchup del
    # proyecto también dan señal para ese ítem contra esos enemigos.
    senal_datos = {iid: _bonus_counter(iid, heroes_enemigos, conoc, cfg, indice)
                   for iid in situacionales.SITUACIONALES}
    if cfg.get("contexto_activo", True):
        ctx_puntos, ctx_razones = situacionales.bonus_contexto(
            heroes_enemigos, senal_datos=senal_datos)
    else:
        ctx_puntos, ctx_razones = {}, {}
    gan = (ganancias_contexto(estado, econ, heroes_enemigos, cfg)
           if cfg.get("contexto_activo", True) else dict(GANANCIAS_NEUTRAS))
    # pesos por contexto: la misma fórmula con w_lift, w_counter, w_precio, w_flujo,
    # w_cadena y w_venta multiplicados por su ganancia. Se aplica como diferencia
    # acotada contra el score base, así el contexto desempata y no reescribe el ranking.
    pesos = {k: cfg["w_" + k] for k in ("lift", "counter", "precio", "flujo", "cadena", "venta")}
    pesos_ctx = {k: v * gan.get(k, 1.0) for k, v in pesos.items()}
    delta_max = cfg.get("contexto_delta", 1.0)

    # Lo que ya lleva puesto puede ser componente de lo que se recomienda: Deadlock
    # consume los componentes y solo cobra la diferencia, liberando sus slots. Antes el
    # motor cobraba el precio de lista y pedía slot libre, así que con Extra Health en la
    # mochila Colossus parecía imposible sin vender (reportado jugando el 2026-11-08).
    _absorbe_cache: dict[str, set] = {}

    def _absorbe(iid):
        if iid not in _absorbe_cache:
            _absorbe_cache[iid] = {c for c in componentes_de([iid]) if c in poseidos}
        return _absorbe_cache[iid]

    def _costo_de(xid):
        return (conoc["items"].get(xid) or {}).get("costo") or 0

    def _slot_de(xid):
        return (conoc["items"].get(xid) or {}).get("slot") or (cat.get(xid) or {}).get("slot")

    def _nombre_de(xid):
        return ((conoc["items"].get(xid) or {}).get("nombre")
                or (cat.get(xid) or {}).get("nombre") or str(xid))

    def _puntaje(w, residual, counter, precio, pareja, bonus_flujo, cadena, castigo_venta):
        """Los términos que llevan peso; se evalúa dos veces (pesos de siempre y
        pesos por contexto) y la diferencia es lo que el contexto puede mover."""
        return (w["lift"]*residual*100
                + w["counter"]*counter*100
                + w["precio"]*precio
                + pareja*100*0.5
                + w["flujo"]*bonus_flujo*10
                + w["cadena"]*cadena*10
                + w["venta"]*castigo_venta)

    filas = []
    for iid, d in conoc["items"].items():
        if iid in poseidos:
            continue
        if iid in ya_superados:
            continue
        c = cat.get(iid, {})
        if not c.get("comprable", True):
            continue
        costo_lista = d["costo"] or c.get("costo") or 0
        absorbe = _absorbe(iid)
        ahorro = sum(_costo_de(x) for x in absorbe)
        costo = max(0, costo_lista - ahorro)     # solo se paga la diferencia
        slot = d["slot"] or c.get("slot")
        if not slot:
            continue
        residual = d["lift_residual"]
        contexto_pts = ctx_puntos.get(iid, 0.0)
        if residual < cfg["lift_minimo"] and contexto_pts <= 0:
            continue
        # En la apertura sólo se abre con ítems de apertura reales, pero la restricción
        # se apaga en rampa en vez de cortarse en el minuto 10 de golpe.
        castigo_apertura = 0.0
        if peso_ap > 0 and iid not in apertura:
            if t_efectivo < cfg.get("apertura_desde_s", 480.0):
                continue
            castigo_apertura = cfg.get("w_apertura", 6.0) * peso_ap
        # los ítems que aparecen en la fase actual del grafo reciben su ventaja real
        info_fase = en_fase.get(iid)
        bonus_flujo = (info_fase["wr_ajustado"] - 0.5) if info_fase else -0.02
        # penalización por tiempo, suave pero fuerte: un ítem de minuto 80 a los 10 se cae solo
        t_rel = (t_efectivo / cfg["duracion_tipica_s"]) * 100.0
        mc = d.get("min_compra") if d.get("min_compra") is not None else t_rel
        distancia_t = abs(t_rel - mc)

        # Los componentes absorbidos que ocupan el mismo slot devuelven su hueco:
        # upgrade sobre lo que ya llevas no necesita vender nada.
        libera = sum(1 for x in absorbe if _slot_de(x) == slot)
        libre = cap.get(slot, 4) - usados.get(slot, 0) + libera
        requiere_venta = False
        if libre <= 0:
            # slot lleno: se permite si hay algo vendible en ese slot (swap)
            vendibles = [i for i in poseidos if (cat.get(i) or {}).get("slot") == slot
                         and conoc["items"].get(i, {}).get("tasa_venta", 0) >= cfg["venta_minima_tasa"]]
            if not vendibles:
                continue
            requiere_venta = True
        # No se descarta lo que hoy no se paga: `recomendar()` saca de aquí el objetivo
        # ("faltan N") con el mismo coste efectivo y los mismos huecos que el ranking.
        alcanzable = costo <= almas

        counter = senal_datos[iid] if iid in senal_datos else _bonus_counter(
            iid, heroes_enemigos, conoc, cfg, indice)
        pareja = _bonus_pareja(iid, poseidos, conoc)
        cadena = _bonus_cadena(iid, poseidos, conoc)
        precio = 1.0 - min(1.0, costo / max(1, almas))   # premia no gastarte todo

        # Gasto por encima de lo que falta para el hito de build: si estás a 400 almas
        # del Early (8,000), comprar un ítem de 6,400 te saca del spike.
        castigo_presupuesto = 0.0
        if faltan_fase and faltan_fase > 0 and costo > faltan_fase:
            castigo_presupuesto = cfg["w_presupuesto"] * (costo - faltan_fase) / 1000.0
        # Yendo atrás, los ítems caros rinden menos que dos de 1,600 (hallazgo 8 de la
        # investigación del 2026-11-07, con fuente en informes/).
        castigo_recuperacion = 0.0
        if atras and costo > cfg["recuperacion_desde"]:
            castigo_recuperacion = cfg["w_recuperacion"]

        # Balance de slots: Deadlock pide las tres categorías al día. Un build con 4 de
        # arma y 0 de vitalidad pierde igual que uno sin ítems, así que se premia
        # rellenar el slot más vacío frente al que ya está lleno.
        hueco = max(0, cap.get(slot, 4) - usados.get(slot, 0))
        hueco_max = max(1, max((cap.get(s, 4) - usados.get(s, 0)) for s in cap))
        premio_balance = cfg.get("w_balance", 0.0) * (hueco / hueco_max) * 2.0
        # Bonus de categoría (4,800): empujón pequeño y solo si falta poco. No manda
        # sobre el camino ni convierte el build en uno genérico.
        premio_bonus = 0.0
        falta_bonus = 4800 - gastado.get(slot, 0)
        if 0 < falta_bonus <= 1000:
            premio_bonus = cfg.get("w_bonus_categoria", 0.0) * (1.0 - falta_bonus / 1000.0)

        # Dos ítems a menos de `empate_margen` puntos son indistinguibles para el jugador,
        # y en ese empate ganaba siempre el primero del diccionario de conocimiento.json,
        # así que el panel repetía el mismo ítem. El desempate premia lo que ya está medio
        # pagado (tener el componente es pagar la diferencia) y lo que deja más caja.
        # Suma acotada a 1 y multiplicada por `empate_margen`: nunca pasa del margen, así
        # que no puede reescribir el ranking. No mira el reloj ni usa azar: el mismo
        # estado da siempre la misma recomendación (invariante de los 10 s).
        ahorro_frac = (ahorro / costo_lista) if costo_lista else 0.0
        caja_frac = 1.0 - min(1.0, costo / max(1, almas))
        premio_caja = cfg["empate_margen"] * _acotar(ahorro_frac + caja_frac)

        # todo en puntos porcentuales para que los pesos sean legibles
        castigo_venta = -1.0 if requiere_venta else 0.0
        base = _puntaje(pesos, residual, counter, precio, pareja, bonus_flujo, cadena,
                        castigo_venta)
        din = _puntaje(pesos_ctx, residual, counter, precio, pareja, bonus_flujo, cadena,
                       castigo_venta)
        score = (base
                 + _acotar(din - base, -delta_max, delta_max)
                 - cfg["w_tiempo"]*distancia_t
                 - castigo_apertura
                 - castigo_presupuesto
                 - castigo_recuperacion
                 + contexto_pts
                 + premio_balance
                 + premio_bonus
                 + premio_caja)

        # `min_compra` viene en porcentaje de la partida típica (0-100), no en minutos:
        # el panel llegó a decir "minuto 61 de partida" a los 25 minutos reales.
        mc_min = (mc or 0) * cfg["duracion_tipica_s"] / 6000.0
        razones = explicador.razones(
            residual=residual, counter=counter, pareja=pareja, cadena=cadena,
            info_fase=info_fase, min_compra=mc_min, distancia_t=distancia_t,
            requiere_venta=requiere_venta, slot=slot,
            contexto=ctx_razones.get(iid), presupuesto=(
                f"cabe en lo que falta para el hito de {hito:,} almas" if (
                    hito and costo <= faltan_fase) else None),
            t_s=t_efectivo, almas=almas, faltan_fase=faltan_fase, heroe=heroe)
        if ahorro:
            nombres = ", ".join(sorted(_nombre_de(x) for x in absorbe))
            razones.append(f"aprovecha lo que ya llevas ({nombres}): "
                           f"pagas {costo:,} en vez de {costo_lista:,}")
        # Con el peso contextual el panel puede decir por qué el número no es el global.
        ajuste = motivo_ganancia(gan)
        if ajuste and abs(gan["lift"] - 1.0) >= 0.02:
            razones.append(ajuste)

        filas.append({"id": iid, "nombre": d["nombre"], "costo": costo, "slot": slot,
                      "score": round(score, 4), "residual": residual, "n": d["n"],
                      "razones": razones, "alcanzable": alcanzable,
                      # el coeficiente que ve el jugador: residual × ganancia del contexto
                      "peso_lift": round(gan["lift"], 3),
                      "coef_pp": round(residual*100*gan["lift"], 2),
                      "costo_lista": costo_lista, "ahorro": ahorro,
                      "absorbe": sorted(_nombre_de(x) for x in absorbe),
                      "min_compra": d.get("min_compra"),
                      "fase": info_fase["wr_ajustado"] if info_fase else None,
                      "requiere_venta": requiere_venta,
                      "icono": d.get("icono") or f"/icono/{iid}"})

    # Orden por score. El desempate de los empates ya está dentro del score (`premio_caja`),
    # así que `filas` queda ordenada para el objetivo y para el ranking a la vez.
    filas.sort(key=lambda x: (-x["score"], x["costo"], x["id"]))
    return [f for f in filas if f["alcanzable"]][:limite], filas


def _peor_vendible(estado, conoc, cat, cfg, slot):
    """El peor ítem del slot que además se vende de verdad en partidas reales."""
    t_rel = (estado.t / cfg["duracion_tipica_s"]) * 100.0
    en_slot = [str(i) for i in estado.yo.items if (cat.get(str(i)) or {}).get("slot") == slot]
    if not en_slot:
        return None, None
    en_slot.sort(key=lambda i: conoc["items"].get(i, {}).get("lift_residual", -1))
    for cand in en_slot:
        info = conoc["items"].get(cand, {})
        if info.get("tasa_venta", 0) < cfg["venta_minima_tasa"]:
            continue
        if info.get("min_venta") and t_rel < info["min_venta"] - cfg["venta_margen_s"]/60:
            continue
        return cand, info
    return None, None


def sugerir_venta(estado: Estado, conoc, cat, cfg=CFG_DEFECTO, filas=None):
    """Propone vender solo cuando un slot está lleno y lo que entra es claramente mejor.

    En Deadlock todo ítem se vende por su valor completo, así que la pregunta no es
    "¿puedo?", sino "¿mejoro la decisión?". La regla exige tres cosas a la vez:
      1. el ítem que entra supera al que sale por al menos `venta_margen_pp`
      2. el ítem que sale se vende de verdad en partidas reales (tasa_venta)
      3. ya pasó su minuto típico de venta

    El que entra ya no se recalcula aquí: sale de las filas de `candidatos()`, que traen
    coste efectivo (componentes que ya llevas), huecos que libera el upgrade y score con
    contexto. Antes esta función tenía su propia fórmula con sólo residual y counter, así
    que podía proponer lo contrario que el ranking (medido: 29 candidatos pedían venta y
    la venta devolvía None). Una fórmula, no dos.
    """
    almas = estado.yo.almas or 0
    if filas is None:
        filas = candidatos(estado, conoc, cat, cfg)[1]
    for f in filas:
        if not f["requiere_venta"] or not f["alcanzable"]:
            continue
        # El coste de lista es el que cuenta para el invariante de caja de la app: no se
        # propone vender para un ítem que ni con el descuento de componentes alcanzaría.
        if f["costo_lista"] > almas:
            continue
        peor, info_peor = _peor_vendible(estado, conoc, cat, cfg, f["slot"])
        if not peor or peor == f["id"]:
            continue
        mejora_pp = (f["residual"] - info_peor.get("lift_residual", -1)) * 100
        if mejora_pp < cfg["venta_margen_pp"]:
            continue
        nombre_peor = info_peor.get("nombre", peor)
        motivo = (f"{f['nombre']} supera a {nombre_peor} por {mejora_pp:+.1f}pp y "
                  f"{nombre_peor} se vende en {info_peor.get('tasa_venta', 0)*100:.0f}% "
                  f"de las partidas")
        if f["ahorro"]:
            motivo += (f"; pagas {f['costo']:,} por lo que ya llevas "
                       f"(lista {f['costo_lista']:,})")
        return {"vender": peor, "nombre": nombre_peor, "slot": f["slot"],
                "comprar": f["id"], "para": f["nombre"], "costo": f["costo"],
                "ahorro": f["ahorro"], "ganancia_pp": round(mejora_pp, 2),
                "se_vende": f"{info_peor.get('tasa_venta',0)*100:.0f}% de las partidas",
                "motivo": motivo}
    return None


def recomendar(estado: Estado, conoc, cat, cfg=None):
    cfg = cfg or CFG_DEFECTO
    # El héroe sale del estado. Si no hay datos suyos en data/heroes/, se usan los de
    # Abrams: la app nunca se queda sin decidir.
    h = heroes.cargar(estado.yo.heroe or "abrams")
    econ = economia(estado)
    tactico = estado_tactico(estado, econ, cfg)
    # 10 candidatos: el panel filtra por oro y así puede ofrecer algo comprable
    # en vez de enseñar siempre un tier 4 que no alcanza.
    top, filas = candidatos(estado, conoc, cat, cfg, limite=10, heroe=h)
    venta = sugerir_venta(estado, conoc, cat, cfg, filas)
    poseidos = {str(i) for i in estado.yo.items}
    # Una venta de algo que ya no está en el inventario es basura: si el estado cambió
    # entre la lectura y el cálculo, se descarta.
    if venta and str(venta.get("vender")) not in poseidos:
        venta = None
    almas = estado.yo.almas or 0
    # Counter de composición: se calcula con la misma señal de datos que el ranking
    # (matchup de 1.9 M de partidas) y la composición enemiga.
    heroes_enemigos = [j.heroe for j in estado.enemigos if j.heroe]
    indice = conoc.get("heroes_index", {})
    senal_datos = {iid: _bonus_counter(iid, heroes_enemigos, conoc, cfg, indice)
                   for iid in situacionales.SITUACIONALES}
    ctx_puntos, ctx_razones = situacionales.bonus_contexto(
        heroes_enemigos, senal_datos=senal_datos)
    contra = {iid: {"puntos": puntos, "razon": ctx_razones.get(iid, "")}
              for iid, puntos in ctx_puntos.items()}
    decision = camino_mod.decidir(estado, conoc, cat, cfg, heroe=h, venta=venta,
                                  contra=contra)
    # La venta solo se enseña si es para el ítem que de verdad toca comprar.
    if venta and decision.get("item") and str(venta.get("comprar")) != str(decision["item"]["id"]):
        venta = None

    def _fila(iid):
        return next((f for f in filas if f["id"] == str(iid)), None)

    # La recomendación principal es el siguiente paso del camino, no el ítem más
    # barato que quepa. Si toca ahorrar, el objetivo sube igual: el panel enseña
    # cuánto falta y el ETA en vez de empujarte a otro 800.
    if decision.get("item"):
        iid = str(decision["item"]["id"])
        fila = _fila(iid)
        if fila is None:
            d = decision["item"]
            fila = {"id": iid, "nombre": d["nombre"], "costo": d["costo"],
                    "slot": (conoc["items"].get(iid) or {}).get("slot"),
                    "score": 0.0, "residual": 0.0, "n": 0,
                    "razones": [decision.get("motivo") or ""], "alcanzable": False,
                    "peso_lift": 1.0, "coef_pp": 0.0,
                    "costo_lista": d.get("costo_lista", d["costo"]),
                    "ahorro": d.get("ahorro", 0), "absorbe": [],
                    "min_compra": None, "fase": None, "requiere_venta": False,
                    "icono": d.get("icono")}
            filas = [fila] + filas
        fila = dict(fila)
        fila.update({"accion": decision["accion"], "modo": decision.get("modo"),
                     "eta_s": decision.get("eta_s"), "faltan": decision.get("faltan")})
        if decision.get("motivo"):
            fila["razones"] = [decision["motivo"]] + [
                r for r in (fila.get("razones") or []) if r != decision["motivo"]]
        top = [fila] + [f for f in top if f["id"] != iid]
        # El ranking viejo usa patrimonio; comprar se paga con lo que queda en el
        # bolsillo. Se descartan las alternativas que no se pagan, salvo el objetivo
        # de AHORRAR, que se enseña con su "faltan".
        _bolsillo = decision.get("bolsillo")
        if _bolsillo is not None:
            top = [f for f in top
                   if (f.get("costo") or 0) <= _bolsillo or f["id"] == iid]
        top = top[:3]
    # objetivo: lo mejor que todavía no puedes pagar, de la misma lista y con el mismo
    # coste efectivo que el ranking (componentes que ya llevas = pagas la diferencia).
    # Antes repetía el filtrado con otra regla (`dist > 30`) y cobraba precio de lista.
    objetivo = None
    # `objetivo` es, por contrato con la UI y con las invariantes, lo que todavía NO
    # se puede pagar. Si el paso del camino ya se paga, la acción es COMPRAR y no hay
    # objetivo pendiente.
    if decision.get("objetivo") and decision.get("faltan", 0) > 0:
        d = decision["objetivo"]
        f = _fila(d["id"]) or {}
        objetivo = {"id": str(d["id"]), "nombre": d["nombre"], "costo": d["costo"],
                    "faltan": decision.get("faltan", max(0, d["costo"] - almas)),
                    "ahorro": d.get("ahorro", 0),
                    "residual": f.get("residual", 0.0), "icono": d.get("icono")}
    else:
        for f in filas:
            if f["alcanzable"] or f["residual"] < cfg["lift_minimo"]:
                continue
            objetivo = {"id": f["id"], "nombre": f["nombre"], "costo": f["costo"],
                        "faltan": f["costo"] - almas, "ahorro": f["ahorro"],
                        "residual": f["residual"], "icono": f["icono"]}
            break

    # plan: los dos pasos siguientes del build. Sale del grafo real de compras (lo que
    # suele venir justo después de la recomendada, con su número de veces) y pasa por la
    # misma cuenta de componentes que el ranking: lo que ya llevas puesto no entra, lo que
    # ya superaste tampoco, y el precio es el efectivo (comprar el componente de algo que
    # ya llevas es pagar sólo la diferencia).
    siguiente = (conoc.get("flujo") or {}).get("siguiente") or {}
    poseidos = {str(i) for i in estado.yo.items}
    ya_superados = componentes_de(poseidos)
    plan = []
    for s in (siguiente.get(top[0]["id"], []) if top else []):
        iid = str(s["id"])
        info = conoc["items"].get(iid)
        if not info or iid in poseidos or iid in ya_superados:
            continue
        if not (cat.get(iid) or {}).get("comprable", True):
            continue
        absorbe = componentes_de([iid]) & poseidos
        ahorro = sum((conoc["items"].get(x) or {}).get("costo") or 0 for x in absorbe)
        plan.append({"id": iid, "nombre": info["nombre"], "n": s["n"],
                     "costo": max(0, (info["costo"] or 0) - ahorro), "ahorro": ahorro,
                     "icono": f"/icono/{iid}"})
        if len(plan) >= 2:
            break
    enemigos = []
    for j in estado.enemigos:
        if not j.heroe:
            continue
        clave = str(j.heroe).lower().replace(" ", "_").replace("-", "_")
        enemigos.append({"heroe": j.heroe, "icono": f"/icono-heroe/{clave}",
                         "almas": j.almas, "bajas": j.bajas,
                         "muertes": j.muertes, "asistencias": j.asistencias})
    aliados = [{"heroe": j.heroe, "almas": j.almas, "bajas": j.bajas,
                "muertes": j.muertes, "asistencias": j.asistencias}
               for j in estado.aliados if (j.heroe or j.almas is not None)]
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
    contexto_fase = explicador.explicar_estado(econ, tactico, estado.t, estado.yo.almas, h)
    # Consejo de composición: va aparte del ranking porque los datos de residual de estos
    # ítems son negativos (los compra quien va perdiendo). Se muestran con su fuente y con
    # el coeficiente a la vista: sin el número, el panel parecía respaldarlos.
    residuales = {iid: d.get("lift_residual") for iid, d in conoc["items"].items()}
    heroes_enemigos = [j.heroe for j in estado.enemigos if j.heroe]
    # El coeficiente de esta lista es el contextual: el mismo `lift_residual` de 1.9 M de
    # partidas multiplicado por la ganancia del estado, igual que en el ranking. Antes era
    # el número global y no se movía nunca con la partida.
    gan = (ganancias_contexto(estado, econ, heroes_enemigos, cfg)
           if cfg.get("contexto_activo", True) else dict(GANANCIAS_NEUTRAS))
    contra = situacionales.sugerencias_composicion(
        heroes_enemigos, estado.yo.items, residuales=residuales,
        ganancia=gan["lift"], motivo_ajuste=motivo_ganancia(gan))
    # Huecos por categoría: el panel puede decir "3/4 weapon" sin recalcular nada.
    slots = {}
    categorias = {}
    for categoria, tope in (cfg.get("slots") or {}).items():
        # El broadcast devuelve a veces el componente y el ítem mejorado a la vez, así que
        # salían cuentas imposibles como «vitalidad 6/4» (visto el 2026-11-09). El juego
        # no puede tener más de 4: se acota, y el número crudo queda en `brutos` para
        # quien quiera mirar la fuente.
        brutos = sum(1 for iid in poseidos
                     if (conoc["items"].get(iid) or {}).get("slot") == categoria)
        usados = min(int(tope), brutos)
        gastado_cat = sum((conoc["items"].get(iid) or {}).get("costo") or 0
                          for iid in poseidos
                          if (conoc["items"].get(iid) or {}).get("slot") == categoria)
        slots[categoria] = {"usados": usados, "total": int(tope),
                            "libres": max(0, int(tope) - usados),
                            "brutos": brutos}
        categorias[categoria] = {
            "gastado": gastado_cat,
            "umbral": 4800,
            "falta": max(0, 4800 - gastado_cat),
            "bonus": gastado_cat >= 4800,
        }

    return {
        "t": estado.t,
        "estado": tactico,
        "contexto_fase": contexto_fase,
        "contra_composicion": contra,
        "fase_economica": patrones.fase_economica(estado.yo.almas, h),
        "heroe_datos": h.datos.get("clave") if hasattr(h, "datos") else None,
        "economia": econ,
        "recomendaciones": top,
        "venta": venta,
        "decision": decision,
        "slots": slots,
        "categorias": categorias,
        "bolsillo": decision.get("bolsillo"),
        "camino": decision.get("camino") or [],
        "plan": plan,
        "objetivo": objetivo,
        "enemigos": enemigos,
        "aliados": aliados,
        "inventario": inventario,
        "almas": estado.yo.almas,
        "confianza": estado.confianza,
        "notas": estado.notas,
    }
