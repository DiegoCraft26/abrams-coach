"""Motor de decisión: qué comprar, qué vender y si farmear o pelear."""
import json
import os

from .decision import camino as camino_mod
from .decision import amenazas as amenazas_mod
from .decision import explicador, heroe as heroes, patrones, perfil as perfil_mod
from .decision import situacionales
from .decision import ventas as ventas_mod
from .estado import Estado
from . import objetivos as objetivos_mod

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A/B de una hipótesis del meta sin tocar código: ABRAMS_FORZAR="id1,id2".
_FORZAR = [x.strip() for x in (os.environ.get("ABRAMS_FORZAR") or "").split(",") if x.strip()]
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
    "forzar_items": list(_FORZAR),  # solo para A/B (ver camino.CFG_CAMINO)
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


def candidatos(estado: Estado, conoc, cat, cfg=CFG_DEFECTO, limite=3, heroe=None,
               amenazas=None):
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
            heroes_enemigos, senal_datos=senal_datos, amenazas=amenazas)
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


def tasa_almas_historial(historial, ventana_s=90.0):
    """Almas/s medidas en esta partida con las últimas muestras del bucle.

    Por qué: el ETA del panel se calculaba con el benchmark del héroe, así que decía
    «faltan 40 s» aunque el jugador fuera a otro ritmo. Diego (2026-11-16): «afecta que
    no esté tan actualizado el timer de souls, sí cambia decisiones justo cuando sabes
    que tienes al menos para el siguiente tier». Con la tasa real, el ETA responde a lo
    que de verdad entra por segundo.

    La ventana es de 90 s de reloj de partida: más corta la vuelve ruidosa (una ola o
    una kill la duplican), más larga deja de reflejar el late. Si no hay muestras
    suficientes o la tasa no es creíble, se devuelve None y el motor usa el benchmark.
    """
    muestras = [m for m in (historial or [])
                if isinstance(m, dict) and m.get("t") is not None
                and m.get("a") is not None]
    if len(muestras) < 3:
        return None
    ultimo = muestras[-1]
    t1, a1 = float(ultimo["t"]), float(ultimo["a"])
    referencia = next((m for m in reversed(muestras)
                       if t1 - float(m["t"]) >= ventana_s), muestras[0])
    t0, a0 = float(referencia["t"]), float(referencia["a"])
    dt = t1 - t0
    if dt < 20.0:
        return None
    tasa = (a1 - a0) / dt
    # Techo: una recompra o un cambio de patrimonio no son 90 almas/s sostenidas.
    if not (0.5 <= tasa <= 90.0):
        return None
    return tasa


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


def _contra_del_estado(estado: Estado, conoc, cfg, amenazas):
    """Counters de composición + qué rival concreto está ganando la partida.

    Devuelve {item_id: {puntos, razon, amenaza}} donde `amenaza` es el nombre del rival
    que va por encima y que ese ítem frena. `camino._objetivo` usa ese campo para no
    frenar el counter con la ventana de fase: si el rival crítico suena, se compra.
    """
    heroes_enemigos = [j.heroe for j in estado.enemigos if j.heroe]
    indice = conoc.get("heroes_index", {})
    senal_datos = {iid: _bonus_counter(iid, heroes_enemigos, conoc, cfg, indice)
                   for iid in situacionales.SITUACIONALES}
    puntos, razones = situacionales.bonus_contexto(
        heroes_enemigos, senal_datos=senal_datos, amenazas=amenazas)
    criticos = [a for a in (amenazas or ()) if a.get("nivel") == "critico"]
    salida = {}
    for iid, valor in puntos.items():
        señal = situacionales.SEÑAL_DE_TAG.get(
            (situacionales.SITUACIONALES.get(iid) or {}).get("tag"))
        rival = next((a.get("heroe") for a in criticos
                      if señal and señal in situacionales.tags_de_heroe(a.get("heroe"))),
                     None)
        salida[iid] = {"puntos": valor, "razon": razones.get(iid, ""),
                       "amenaza": rival}
    return salida


# --- perfil histórico de riesgo -------------------------------------------------
# Fuente: informes/lab/REGLAS-VALIDADAS-2026-11-18.md — 3 538 partidas de Abrams en
# ranked de la temporada 2 (match-history de 540 cuentas, hero_id=6, match_mode=4).
# Es **descriptivo**: en las partidas que se ganan se muere menos y se participa más.
# La UI lo enseña como contexto histórico, nunca como predicción.
MUERTES_META = 6
PART_META = 0.40
RIESGO_MIN_S = 300          # antes del minuto 5 los cortes no dicen nada de la partida
# Mismo umbral que `servidor.UMBRAL_RANCIO_S`; el test de contrato obliga a que no se
# separen (un aviso «en vivo» con datos de hace 8 s ya no es en vivo).
EDAD_RANCIO_S = 8.0
CONTEXTO_RIESGO = ("≤6 muertes: 76.9 % vs 36.2 % · ≥0.40: 70.9 % vs 12.8 % "
                   "(n=3 538)")


def riesgo_de(estado: Estado, vivo=True):
    """Perfil histórico de la partida, o None si no hay señal que lo sostenga.

    Devuelve `{muertes, participacion, muertes_meta, part_meta, cruza_muertes,
    bajo_participacion, contexto}`. Nada más: los dos cortes, sus metas y el contexto
    con su n, para que el panel pueda decir «7 muertes · meta ≤6» y llevar el
    histórico en el `title`.

    Es None —no un cero— cuando la partida no lo sostiene:
      · reloj menor a 5 min (`RIESGO_MIN_S`): con una sola pelea la participación se
        dispara y el corte no informa de nada;
      · sin KDA (`estado.con_kda`): la pantalla y el OCR no traen bajas, muertes ni
        asistencias y publican ceros de relleno;
      · datos viejos (`vivo=False`): un contexto de hace medio minuto no es contexto
        vivo, y el panel se mira entre peleas como si lo fuera.
    """
    if not vivo:
        return None
    if not getattr(estado, "con_kda", False):
        return None
    t = float(estado.t or 0)
    if t < RIESGO_MIN_S:
        return None
    minutos = t / 60.0
    muertes = int(estado.yo.muertes or 0)
    participacion = (int(estado.yo.bajas or 0)
                     + int(estado.yo.asistencias or 0)) / minutos
    # Las comparaciones usan el valor sin redondear: 6/15 = 0.40 exacto no es «bajo».
    return {
        "muertes": muertes,
        "participacion": round(participacion, 2),
        "muertes_meta": MUERTES_META,
        "part_meta": PART_META,
        "cruza_muertes": muertes > MUERTES_META,
        "bajo_participacion": participacion < PART_META,
        "contexto": CONTEXTO_RIESGO,
    }


def recomendar(estado: Estado, conoc, cat, cfg=None, vivo=True):
    cfg = cfg or CFG_DEFECTO
    # El héroe sale del estado. Si no hay datos suyos en data/heroes/, se usan los de
    # Abrams: la app nunca se queda sin decidir.
    h = heroes.cargar(estado.yo.heroe or "abrams")
    econ = economia(estado)
    tactico = estado_tactico(estado, econ, cfg)
    # Amenazas primero: quién del otro equipo está por encima condiciona la compra, y
    # tanto el ranking como el camino necesitan ese dato antes de puntuar nada.
    amenazas = amenazas_mod.evaluar(estado)
    t_ef = (int(max(0.0, float(estado.t))) // 10) * 10.0
    perfil = perfil_mod.calcular(estado, econ, amenazas, t_ef=t_ef,
                                 poseidos={str(i) for i in estado.yo.items})
    # 10 candidatos: el panel filtra por oro y así puede ofrecer algo comprable
    # en vez de enseñar siempre un tier 4 que no alcanza.
    top, filas = candidatos(estado, conoc, cat, cfg, limite=10, heroe=h,
                            amenazas=amenazas["lista"])
    venta = sugerir_venta(estado, conoc, cat, cfg, filas)
    poseidos = {str(i) for i in estado.yo.items}
    # Una venta de algo que ya no está en el inventario es basura: si el estado cambió
    # entre la lectura y el cálculo, se descarta.
    if venta and str(venta.get("vender")) not in poseidos:
        venta = None
    almas = estado.yo.almas or 0
    # Counter de composición: se calcula con la misma señal de datos que el ranking
    # (matchup de 1.9 M de partidas) y la composición enemiga. Si un rival va por
    # encima, su counter pesa más y se nombra.
    heroes_enemigos = [j.heroe for j in estado.enemigos if j.heroe]
    contra = _contra_del_estado(estado, conoc, cfg, amenazas["lista"])
    tasa_medida = tasa_almas_historial(getattr(estado, "historial", None))
    decision = camino_mod.decidir(estado, conoc, cat, cfg, heroe=h, venta=venta,
                                  contra=contra, perfil=perfil, tasa=tasa_medida)
    if tasa_medida:
        # El panel cuenta hacia atrás con este número: se publica para que el ETA no sea
        # un número congelado entre lecturas del broadcast.
        decision["tasa_s"] = round(tasa_medida, 2)
    # Camino agotado: con los 12 slots hay veces que no queda más build que comprar. Antes
    # se decía «build completo» aunque hubiera oro y algo mejor en el ranking; ahora la
    # siguiente pieza sale de ahí, con su cuenta de faltan/ETA.
    if not decision.get("item") and filas:
        # Con el camino agotado, la pieza de refuerzo tiene que ser del tamaño de la
        # partida: un 800 al minuto 25 no arregla nada (el banco lo vio 3,557 veces).
        minimo = 1600 if estado.t >= 1200 else 0
        if estado.t >= 1800:
            minimo = 3200
        caro_ok = estado.t >= 900

        def _vale(x):
            lista = x.get("costo_lista") or x.get("costo") or 0
            if (x.get("costo") or 0) < minimo:
                return False
            if lista >= 6400 and not caro_ok:
                return False
            return True

        f = next((x for x in filas
                  if str(x["id"]) not in poseidos and _vale(x)), None)
        if f is None:
            f = next((x for x in filas if str(x["id"]) not in poseidos), None)
        if f is not None:
            bolsillo = decision.get("bolsillo") or 0
            costo = f.get("costo") or 0
            faltan = max(0, costo - bolsillo)
            tasa = camino_mod.tasa_almas(conoc, h, estado.t, real=tasa_medida)
            eta = int(-(-faltan // max(1.0, tasa))) if faltan else 0
            ficha = {"id": str(f["id"]), "nombre": f["nombre"], "costo": int(costo),
                     "costo_lista": int(f.get("costo_lista") or costo),
                     "ahorro": int(f.get("ahorro") or 0), "icono": f.get("icono")}
            decision = {
                "accion": "AHORRAR" if faltan else "COMPRAR", "modo": "refuerzo",
                "bolsillo": bolsillo, "item": ficha, "objetivo": dict(ficha),
                "faltan": faltan, "eta_s": eta,
                "motivo": (f"camino completo: la siguiente pieza sale del ranking y "
                           f"cuesta {costo:,}"),
                "camino": [], "alternativas": [],
                "perfil": perfil.get("etiqueta"), "perfil_modo": perfil.get("modo"),
                "perfil_motivo": perfil.get("motivo"), "perfil_contra": perfil.get("rival"),
                "target": str(f["id"]), "target_nombre": f["nombre"],
            }
    # Prioridad de venta: qué de lo que llevas sale primero. Se calcula con el camino ya
    # resuelto porque el nivel «ahora» depende de si el build se agotó. Esto es lo que
    # faltaba en late: el panel decía «build completo» y no nombraba nada que soltar.
    ventas = ventas_mod.prioridad(estado, conoc, cfg,
                                  camino_agotado=not (decision.get("camino") or []))
    if not decision.get("item") and ventas:
        p = ventas[0]
        decision = {**decision, "modo": "completo",
                    "motivo": (f"build completo: lo primero que sale es {p['nombre']} "
                               f"({p['slot_nombre']}, {p['pp']:+.1f}pp)"),
                    "vende_prioridad": p["id"]}
    # La venta se calcula para el paso que de verdad toca comprar, no solo para el nº1
    # del ranking. Antes `venta` se anulaba si el paso del camino no era ese ítem y por
    # eso en partida casi nunca aparecía (Diego, 2026-11-15: «debería recomendar ventas
    # específicas y tomarlas en cuenta en el plan»).
    if venta and decision.get("item") and str(venta.get("comprar")) != str(decision["item"]["id"]):
        venta = None

    def _venta_para(iid, exigir_mejora):
        """La venta concreta para meter `iid`: qué sale, de qué slot y por qué.

        Con `exigir_mejora` solo se propone si lo que entra supera a lo que sale por el
        margen del motor. Sin ella (el camino ya decidió que hay que vender) se nombra
        el peor vendible del slot y no se afirma ninguna mejora.
        """
        iid = str(iid)
        slot = (conoc["items"].get(iid) or {}).get("slot")
        if not slot:
            return None
        usados = sum(1 for i in poseidos
                     if (conoc["items"].get(i) or {}).get("slot") == slot)
        if usados < 4:
            return None
        peor, info_peor = _peor_vendible(estado, conoc, cat, cfg, slot)
        if not peor or peor == iid:
            return None
        nombre_peor = (info_peor or {}).get("nombre", peor)
        tasa = ((info_peor or {}).get("tasa_venta") or 0) * 100
        mio = (conoc["items"].get(iid) or {}).get("lift_residual") or 0.0
        mejora = (mio - (info_peor or {}).get("lift_residual", -1.0)) * 100
        if exigir_mejora and mejora < cfg["venta_margen_pp"]:
            return None
        entra = (decision.get("item") or {}).get("nombre") or iid
        motivo = (f"slot {slot} lleno: {entra} supera a {nombre_peor} por {mejora:+.1f}pp"
                  if exigir_mejora else
                  f"slot {slot} lleno: vende {nombre_peor} para meter {entra}")
        return {"vender": peor, "nombre": nombre_peor, "slot": slot,
                "comprar": iid, "para": entra,
                "costo": (decision.get("item") or {}).get("costo"),
                "ahorro": (decision.get("item") or {}).get("ahorro") or 0,
                "ganancia_pp": round(mejora, 2) if exigir_mejora else None,
                "se_vende": f"{tasa:.0f}% de las partidas",
                "motivo": motivo}

    if decision.get("item"):
        iid_dec = str(decision["item"]["id"])
        bolsillo_dec = decision.get("bolsillo") or 0
        costo_dec = (decision.get("item") or {}).get("costo") or 0
        # Solo se nombra la venta cuando el ítem ya se paga: si no, es una orden que
        # no se puede ejecutar (y el invariante de caja la marca como compra imposible).
        if venta is None and costo_dec <= bolsillo_dec:
            venta = _venta_para(iid_dec, exigir_mejora=False)
        # Vender para pagar: con el slot lleno, el hueco vale el precio completo del ítem
        # que sale. Antes, con 3 600 almas y un 6 400 pendiente, el panel decía «faltan
        # 2 800» aunque soltando una pieza ya llegabas a comprarlo.
        lista_dec = (decision.get("item") or {}).get("costo_lista") or costo_dec
        if venta is None and costo_dec > bolsillo_dec and lista_dec <= almas:
            # El tope es el patrimonio (almas), no el bolsillo: vender no crea almas,
            # solo las mueve del ítem que sale. Sin este tope, un estado imposible
            # (12 slots con patrimonio de 900) generaba una compra que no se paga.
            falta_pagar = costo_dec - bolsillo_dec
            for cand in ventas:
                if falta_pagar <= (cand.get("costo") or 0) and cand["slot"] == \
                        (conoc["items"].get(iid_dec) or {}).get("slot"):
                    entra = (decision.get("item") or {}).get("nombre") or iid_dec
                    venta = {"vender": cand["id"], "nombre": cand["nombre"],
                             "slot": cand["slot"], "comprar": iid_dec, "para": entra,
                             "costo": costo_dec,
                             "ahorro": (decision.get("item") or {}).get("ahorro") or 0,
                             "ganancia_pp": None, "vende_pp": cand["pp"],
                             "se_vende": f"{cand['tasa'] * 100:.0f}% de las partidas",
                             "para_pagar": True,
                             "motivo": (f"vende {cand['nombre']} ({cand['slot_nombre']}): "
                                        f"te devuelve {cand['costo']:,} y entras ya a "
                                        f"{entra}")}
                    break
        # VENDER solo cuando de verdad toca hacerlo: el ítem entra y hay que abrir hueco.
        if venta and decision.get("accion") in ("COMPRAR", "AHORRAR"):
            if costo_dec <= bolsillo_dec:
                # El sufijo de la decisión («· a 800 del bonus de spirit») se conserva,
                # pero el nombre que sale lo pone la venta final: antes el motivo decía
                # «vende X» (del ranking) y la venta «vende Y» (del slot del ítem).
                previo = decision.get("motivo") or ""
                cola = previo[previo.find(" · "):] if " · " in previo else ""
                decision = {**decision, "accion": "VENDER", "modo": "slot",
                            "motivo": venta["motivo"] + cola}
            else:
                # No se cambia la acción: todavía no lo pagas, pero el panel ya dice qué
                # vender y que con eso entras. VENDER aquí sería una compra sin pagar.
                decision = {**decision, "modo": "venta-pago",
                            "motivo": venta["motivo"],
                            "vende_prioridad": venta["vender"]}
        # Una venta sin nombres es una orden a ciegas: si no se puede nombrar, no se dice.
        if decision.get("accion") == "VENDER" and not venta:
            decision = {**decision,
                        "accion": "AHORRAR" if (decision.get("faltan") or 0) else "COMPRAR",
                        "modo": "slot-indefinido",
                        "motivo": (f"slot lleno y no hay candidato claro a vender; "
                                   f"revisa el inventario antes de comprar "
                                   f"{decision['item']['nombre']}")}
        if venta:
            # El plan lo tiene en cuenta: el paso que toca se pinta con su venta.
            camino_dec = list(decision.get("camino") or [])
            if camino_dec:
                camino_dec[0] = {**camino_dec[0], "vende": venta["nombre"],
                                 "vende_id": venta["vender"]}
                decision = {**decision, "camino": camino_dec}

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
                    "razones": [decision.get("motivo") or ""],
                    # La fila sintética se marcaba siempre como no alcanzable, y el
                    # objetivo salía con «faltan» negativo (invariante 1 del QA).
                    "alcanzable": d["costo"] <= (decision.get("bolsillo") or 0),
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
            if (f["alcanzable"] or (f.get("costo") or 0) <= almas
                    or f["residual"] < cfg["lift_minimo"]):
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
    # Enemigos con su marca de amenaza: el panel pinta en rojo al que va por encima y
    # escribe "EVITAR" en el que no se busca solo. El orden no cambia (mantiene la
    # posición de la rejilla); la ficha del peligroso se marca, no se reordena.
    ficha_amenaza = {str(a.get("heroe")): a for a in amenazas["lista"] if a.get("heroe")}
    enemigos = []
    for j in estado.enemigos:
        if not j.heroe:
            continue
        clave = str(j.heroe).lower().replace(" ", "_").replace("-", "_")
        a = ficha_amenaza.get(str(j.heroe)) or {}
        enemigos.append({"heroe": j.heroe, "icono": f"/icono-heroe/{clave}",
                         "almas": j.almas, "bajas": j.bajas,
                         "muertes": j.muertes, "asistencias": j.asistencias,
                         "nivel": a.get("nivel"),
                         "delta_pct": (round(a["delta_pct"], 3)
                                       if a.get("delta_pct") is not None else None),
                         "evitar_solo": bool(a.get("evitar_solo")),
                         "motivo": a.get("motivo")})
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
        ganancia=gan["lift"], motivo_ajuste=motivo_ganancia(gan),
        amenazas=amenazas["lista"])
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

    # Objetivos: si el ritmo de almas va por debajo (walkers que no caen), el plan deja
    # de empujar el ahorro fino y pide farmear objetivo. Se calcula con lo que llega por
    # HTTP; si no hay datos suficientes, `prioridad` es False y no se dice nada.
    objetivos = objetivos_mod.evaluar(estado)
    if objetivos.get("prioridad") and decision.get("accion") == "AHORRAR" \
            and decision.get("modo") in ("ahorro", "rush"):
        decision = {**decision, "modo": "farm",
                    "motivo": (decision.get("motivo") or "")
                              + " · vas corto por objetivos"}

    if venta:
        # Un solo «vende esto» a la vez: si el motor ya nombró el ítem, la lista de
        # prioridad se alinea con él. Dos nombres distintos para la misma acción es
        # ruido; el inventario y el aviso tienen que apuntar al mismo slot.
        for v in ventas:
            v["nivel"] = ("ahora" if str(v.get("id")) == str(venta.get("vender"))
                          else "luego")
        if decision.get("accion") == "VENDER" \
                and venta["motivo"] not in (decision.get("motivo") or ""):
            previo = decision.get("motivo") or ""
            cola = previo[previo.find(" · "):] if " · " in previo else ""
            decision = {**decision, "motivo": venta["motivo"] + cola}

    # Evidencia medida del motor v2: se adjunta a la recomendación, no la reordena.
    # El efecto estimado es de 1-2 pp con intervalo ancho; usarlo para reescribir el
    # ranking sería cambiar una heurística medible por otra peor medida. Primero se
    # acumula el desacuerdo en telemetría y se decide con datos (puerta G4).
    evidencia = None
    desacuerdo = None
    valor_modelo = None
    try:
        from . import valor as valor_mod
        valor_modelo = valor_mod.resumen()
        if top:
            evidencia = valor_mod.evidencia(top[0]["id"])
            desacuerdo = valor_mod.comparar(top, cfg["empate_margen"])
        if evidencia and top:
            top = [{**top[0], "evidencia": evidencia}] + list(top[1:])
        if desacuerdo:
            from . import telemetria
            telemetria.anotar("valor_desacuerdo", **desacuerdo)
        # Aviso de desempate: el modelo prefiere otra compra que el motor considera
        # equivalente. No se cambia la recomendación (eso exige mover el camino, la
        # venta y los componentes a la vez); se dice en una línea.
        desempate = valor_mod.preferencia(top, cfg["empate_margen"]) if top else None
    except Exception:                                      # noqa: BLE001
        # Un artefacto ilegible no puede tumbar una recomendación: el motor sigue.
        evidencia, desacuerdo, valor_modelo, desempate = None, None, None, None

    return {
        "t": estado.t,
        "estado": tactico,
        "contexto_fase": contexto_fase,
        "contra_composicion": contra,
        "amenazas": amenazas,
        "perfil": {"etiqueta": perfil.get("etiqueta"), "modo": perfil.get("modo"),
                   "motivo": perfil.get("motivo"), "rival": perfil.get("rival"),
                   "tope": perfil.get("tope")},
        # Perfil histórico de la partida (contexto, no predicción). None sin KDA,
        # antes de 5 min o si el estado que llega ya no es de ahora.
        "riesgo": riesgo_de(estado, vivo),
        "fase_economica": patrones.fase_economica(estado.yo.almas, h),
        "heroe_datos": h.datos.get("clave") if hasattr(h, "datos") else None,
        "economia": econ,
        "recomendaciones": top,
        "venta": venta,
        "ventas": ventas,
        "decision": decision,
        "slots": slots,
        "categorias": categorias,
        "bolsillo": decision.get("bolsillo"),
        "camino": decision.get("camino") or [],
        "plan": plan,
        "objetivo": objetivo,
        "enemigos": enemigos,
        "aliados": aliados,
        "inventario": ventas_mod.anotar(inventario, ventas),
        "almas": estado.yo.almas,
        "tasa_almas_s": round(tasa_medida, 2) if tasa_medida else None,
        "objetivos": objetivos,
        "confianza": estado.confianza,
        "notas": estado.notas,
        "evidencia": evidencia,
        "desempate": desempate,
        "valor_modelo": valor_modelo,
    }
