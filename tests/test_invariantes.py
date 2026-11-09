"""Invariantes del motor de decisión sobre 50 estados sintéticos de partida.

Uso: python3 tests/test_invariantes.py
Sin dependencias. Sale con 0 solo si las 6 invariantes quedan con 0 violaciones.

Invariantes verificadas
  1. NUNCA se sugiere comprar un ítem cuyo coste supere las almas actuales. La
     excepción es el objetivo de una decisión AHORRAR: se enseña a propósito, con
     "faltan" y ETA, porque el panel te dice cuánto juntar (no que lo compres ya).
  2. NUNCA se recomienda un ítem que el jugador ya tiene comprado, ni un
     componente cuyo tier superior ya está completo en el inventario
     (árbol `component_items` de data/items.json).
  3. NUNCA cambia el ítem recomendado con menos de 10 s de partida entre dos
     consultas sobre el mismo estado (incluye determinismo con Δt = 0).
  4. NUNCA se propagan almas imposibles (negativas o > 200000): se rechazan o
     se claman, nunca llegan a economía, estado táctico ni recomendaciones.
  5. Toda decisión trae razones no vacías (recomendaciones, venta, estado).
  6. Latencia media por consulta < 20 ms.

Nota de alcance: `objetivo` es por diseño el ítem que todavía NO se puede
pagar (trae "faltan"), así que queda fuera de la invariante 1.

Si encuentra violaciones, las imprime y escribe informes/qa2-violaciones.md.
No modifica coach/*, run.py ni ningún otro test.
"""
import hashlib, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from coach.motor_api import Motor

N_ESTADOS = 50
ALMAS_VALIDAS = (0, 200, 900, 1500, 3000, 8000, 20000)
ALMAS_MAX = 200000
LATENCIA_MAX_MS = 20.0
VENTANA_S = 10.0

# 50 tiempos repartidos entre 0 y 45 min (0..2700 s), con casos justo a los
# lados de cada frontera de fase (600/1200/1800/2400 s).
TIEMPOS = [
    0, 60, 150, 240, 300, 360, 480, 540, 590, 595,
    600, 605, 700, 840, 900, 1020, 1140, 1190, 1195, 1200,
    1210, 1320, 1440, 1500, 1620, 1740, 1790, 1795, 1800, 1810,
    1920, 2040, 2100, 2220, 2340, 2390, 2395, 2400, 2410, 2520,
    2580, 2600, 2640, 2650, 2660, 2670, 2680, 2690, 2695, 2700,
]

# Δt < 10 s para la invariante 3, rotando para cubrir varios huecos.
DELTAS = (9.5, 8.0, 6.4, 4.0, 2.5, 1.0, 0.4)

# Estados justo por debajo de una frontera de fase (600/1200/1800/2400 s): se
# les da un nivel de almas con el que sí hay recomendaciones a ambos lados, si
# no la invariante 3 no llega a ejercitarse.
ALMAS_EN_BORDE = {8: 3000, 9: 8000, 17: 3000, 18: 8000,
                  26: 3000, 27: 8000, 35: 3000, 36: 8000}

# Almas imposibles que el motor no debe propagar (invariante 4).
ALMAS_IMPOSIBLES = (-1, -500, -1000, 200001, 1000000000)

INVARIANTES = {
    1: "nunca recomienda por encima de las almas",
    2: "nunca recomienda ya comprado / tier superior",
    3: "nunca cambia de ítem con < 10 s",
    4: "nunca propaga almas imposibles",
    5: "las razones nunca van vacías",
    6: "latencia media < 20 ms",
}


# --------------------------------------------------------------------------
# árbol de componentes: qué tier superior se construye con cada ítem
# --------------------------------------------------------------------------
def arbol_tier_superior():
    """Mapa componente → ítems que se construyen con él.

    data/items.json trae `component_items` (class_name de los componentes) y
    cada ítem su `class_name`, así que el árbol se reconstruye por nombre.
    """
    ruta = os.path.join(BASE, "data", "items.json")
    if not os.path.exists(ruta):
        return {}
    try:
        crudo = json.load(open(ruta))
    except Exception:
        return {}
    if not isinstance(crudo, dict):
        return {}
    clase_a_id = {v.get("class_name"): str(v["id"]) for v in crudo.values()
                  if isinstance(v, dict) and v.get("class_name")}
    directos = {}
    for v in crudo.values():
        if not isinstance(v, dict):
            continue
        comps = [clase_a_id[c] for c in (v.get("component_items") or [])
                 if c in clase_a_id]
        if comps:
            directos[str(v["id"])] = comps
    padres = {}
    for padre, comps in directos.items():
        for c in comps:
            padres.setdefault(c, set()).add(padre)
    return padres


def _desde(arbol, iid, limite=6):
    """Todos los ítems que se construyen (transitivamente) a partir de iid."""
    vistos, cola = set(), [(iid, 0)]
    while cola:
        actual, prof = cola.pop()
        if prof > limite:
            continue
        for padre in arbol.get(actual, ()):
            if padre in vistos:
                continue
            vistos.add(padre)
            cola.append((padre, prof + 1))
    return vistos


# --------------------------------------------------------------------------
# generación de los 50 estados
# --------------------------------------------------------------------------
def _heroes():
    ruta = os.path.join(BASE, "data", "heroes_index.json")
    claves = []
    if os.path.exists(ruta):
        try:
            claves = sorted(json.load(open(ruta)).keys())
        except Exception:
            claves = []
    if not claves:
        claves = ["haze", "lash", "seven", "vindicta", "kelvin", "shiv", "warden"]
    # de "lady_geist" a "Lady Geist": el motor normaliza espacios y guiones
    return [c.replace("_", " ").title() for c in claves]


def _pozas(m, slots):
    """Ítems del conocimiento agrupados por slot (orden estable por id)."""
    pozas = {s: [] for s in slots}
    for iid, d in sorted(m.conoc["items"].items()):
        slot = d.get("slot") or (m.cat.get(iid) or {}).get("slot")
        if slot in pozas:
            pozas[slot].append(iid)
    return pozas


def _con_tier_superior(m, arbol):
    """Dueños válidos para probar la invariante 2: ítems con componentes dentro
    del conocimiento, uno por slot, elegidos de forma determinista."""
    elegidos, vistos = [], set()
    for iid, d in sorted(m.conoc["items"].items()):
        slot = d.get("slot")
        if not slot or slot in vistos:
            continue
        if _desde(arbol, iid) & set(m.conoc["items"]):
            elegidos.append(iid)
            vistos.add(slot)
    return elegidos


def generar_estados(m, arbol):
    """50 estados deterministas: tiempo 0..45 min, 7 niveles de almas,
    héroes aliados/enemigos rotando, slots vacíos / parciales / llenos."""
    heroes = _heroes()
    pozas = _pozas(m, ("weapon", "vitality", "spirit"))
    cap = 4
    estados = []

    for i, t in enumerate(TIEMPOS[:N_ESTADOS]):
        almas = almas_para(i)
        modo = ("vacio", "parcial", "lleno")[i % 3]
        items = []

        if modo == "parcial":
            k = 1 + (i % 3)            # 1..3 ítems por slot elegido
            for j, slot in enumerate(pozas):
                if (i + j) % 2:
                    continue
                pool = pozas[slot]
                if not pool:
                    continue
                for n in range(k):
                    items.append(pool[(i * 7 + j * 13 + n * 11) % len(pool)])
        elif modo == "lleno":
            for j, slot in enumerate(pozas):
                pool = pozas[slot][:max(cap, 8)]
                for n in range(cap):
                    items.append(pool[(i * 5 + j * 17 + n * 3) % len(pool)])

        # el propio jugador no puede llevar duplicados
        items = list(dict.fromkeys(items))

        # enemigos y aliados distintos por estado
        enemigos = []
        for n in range(3):
            h = heroes[(i * 3 + n) % len(heroes)]
            enemigos.append({"heroe": h, "almas": almas + (n - 1) * 300})
        aliados = []
        for n in range(2):
            h = heroes[(i * 5 + n + 7) % len(heroes)]
            aliados.append({"heroe": h, "almas": max(0, almas + (n * 400 - 200))})

        estados.append({
            "t": float(t),
            "yo": {"heroe": "Abrams", "almas": almas, "items": list(items)},
            "aliados": aliados,
            "enemigos": enemigos,
            "confianza": 1.0,
        })

    # 4 estados extra con un tier superior ya comprado (invariante 2)
    duenos = _con_tier_superior(m, arbol)
    for n, dueno in enumerate(duenos[:4]):
        idx = 5 + n * 11
        slot = m.conoc["items"][dueno]["slot"]
        pool = pozas.get(slot, [])
        relleno = [pool[(idx * 3 + k) % len(pool)] for k in range(2)] if pool else []
        items = list(dict.fromkeys([dueno] + relleno + list(estados[idx]["yo"]["items"])[:4]))
        estados[idx] = {
            "t": float(TIEMPOS[idx]),
            "yo": {"heroe": "Abrams", "almas": almas_para(idx), "items": items},
            "aliados": estados[idx]["aliados"],
            "enemigos": estados[idx]["enemigos"],
            "confianza": 1.0,
        }
    return estados


def almas_para(i):
    return ALMAS_EN_BORDE.get(i, ALMAS_VALIDAS[i % len(ALMAS_VALIDAS)])


def delta_para(t, i):
    """Δt < 10 s. Si hay una frontera de fase a menos de 9.5 s, se cruza: ese es
    el caso límite de la invariante 3 (dos consultas casi seguidas que caen a
    lados distintos del minuto 10/20/30/40)."""
    borde = (int(t // 600) + 1) * 600
    if 0 < borde - t < VENTANA_S - 0.5:
        return borde - t + 0.5
    return DELTAS[i % len(DELTAS)]


def etiqueta(i, est):
    return (f"S{i:02d} t={est['t']:.0f}s almas={est['yo']['almas']} "
            f"items={len(est['yo']['items'])}")


# --------------------------------------------------------------------------
# infraestructura de medición
# --------------------------------------------------------------------------
def medir(m, est):
    t0 = time.perf_counter()
    r = m.analizar_dict(est)
    ms = (time.perf_counter() - t0) * 1000.0
    return r, ms


def top(r):
    recs = r.get("recomendaciones") or []
    return recs[0]["id"] if recs else None


def _firma(r):
    """Lo que la app toma como decisión: estado táctico + ítems recomendados."""
    return (str((r.get("estado") or {}).get("estado")),
            tuple(x["id"] for x in (r.get("recomendaciones") or [])),
            (r.get("venta") or {}).get("comprar"))


def nombre(m, iid):
    return (m.conoc["items"].get(str(iid)) or {}).get("nombre", str(iid))


def _sha(ruta):
    """Huella corta del archivo para saber contra qué versión se midió."""
    try:
        with open(ruta, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except Exception:
        return "?"


def main():
    t_arranque = time.perf_counter()
    m = Motor()
    arbol = arbol_tier_superior()
    estados = generar_estados(m, arbol)

    viol = {k: [] for k in INVARIANTES}
    revisado = {k: 0 for k in INVARIANTES}
    latencias = []

    # calentamiento (no se mide)
    medir(m, estados[0])

    resultados = []
    for i, est in enumerate(estados):
        r, ms = medir(m, est)
        latencias.append(ms)
        resultados.append(r)

    # ---- 1 y 2: coste y recompra, sobre recomendaciones y venta ----------
    for i, (est, r) in enumerate(zip(estados, resultados)):
        almas = est["yo"]["almas"] or 0
        # El motor decide con lo que puedes gastar: oro, o patrimonio menos lo que
        # costó el inventario. Comparar contra el patrimonio neto marcaba como
        # "pagable" un ítem que ya está gastado en los slots.
        bolsillo = r.get("bolsillo")
        if bolsillo is None:
            bolsillo = almas
        poseidos = {str(x) for x in est["yo"]["items"]}
        objetivo = r.get("objetivo")

        for x in r.get("recomendaciones") or []:
            revisado[1] += 1
            # El objetivo de AHORRAR se muestra a propósito aunque no alcance: el
            # panel dice cuánto falta y el ETA. No es una compra sugerida.
            if x["costo"] > bolsillo and not (
                    x.get("accion") == "AHORRAR" and (x.get("faltan") or 0) > 0):
                viol[1].append((etiqueta(i, est),
                                f"recomienda '{x['nombre']}' ({x['costo']} almas) "
                                f"con {bolsillo} en el bolsillo"))
            revisado[2] += 1
            if str(x["id"]) in poseidos:
                viol[2].append((etiqueta(i, est),
                                f"recomienda '{x['nombre']}' que ya está comprado"))
            superiores = _desde(arbol, str(x["id"])) & poseidos
            if superiores:
                nombres = ", ".join(f"'{nombre(m, s)}'" for s in sorted(superiores))
                viol[2].append((etiqueta(i, est),
                                f"recomienda '{x['nombre']}' (tier "
                                f"{(m.conoc['items'].get(x['id']) or {}).get('tier')}) pero su tier "
                                f"superior {nombres} ya está comprado"))

        venta = r.get("venta")
        if venta:
            revisado[1] += 1
            iid = str(venta["comprar"])
            costo = (m.conoc["items"].get(iid) or {}).get("costo") or 0
            if costo > almas:
                viol[1].append((etiqueta(i, est),
                                f"propone cambiar a '{venta['para']}' ({costo} almas) "
                                f"con {bolsillo} en el bolsillo"))
            revisado[2] += 1
            if iid in poseidos:
                viol[2].append((etiqueta(i, est),
                                f"propone cambiar a '{venta['para']}' que ya está comprado"))
            superiores = _desde(arbol, iid) & poseidos
            if superiores:
                nombres = ", ".join(f"'{nombre(m, s)}'" for s in sorted(superiores))
                viol[2].append((etiqueta(i, est),
                                f"propone cambiar a '{venta['para']}' pero su tier "
                                f"superior {nombres} ya está comprado"))

        if objetivo and objetivo["costo"] <= bolsillo:
            viol[1].append((etiqueta(i, est),
                            f"'objetivo' pagable ({objetivo['costo']} <= {almas}) "
                            f"cuando debería ser lo que falta por pagar"))

    # ---- 3: mismo estado, Δt < 10 s --------------------------------------
    for i, (est, r) in enumerate(zip(estados, resultados)):
        revisado[3] += 1
        despues = dict(est)
        despues["t"] = est["t"] + delta_para(est["t"], i)
        r2, ms = medir(m, despues)
        latencias.append(ms)
        a, b = top(r), top(r2)
        if a != b:
            viol[3].append((etiqueta(i, est),
                            f"en {est['t']:.0f}s recomienda '{nombre(m, a)}' "
                            f"({a}) y en {despues['t']:.1f}s "
                            f"(Δt={despues['t'] - est['t']:.1f}s) recomienda "
                            f"'{nombre(m, b)}' ({b}) · top3 "
                            f"{est['t']:.0f}s="
                            f"{[x['nombre'] for x in r['recomendaciones']]}"
                            f" · top3 {despues['t']:.1f}s="
                            f"{[x['nombre'] for x in r2['recomendaciones']]}"))

    # determinismo: la misma consulta dos veces debe dar lo mismo
    for i in range(0, len(estados), 5):
        est = estados[i]
        r3, ms = medir(m, est)
        latencias.append(ms)
        a, b = top(resultados[i]), top(r3)
        revisado[3] += 1
        if a != b:
            viol[3].append((etiqueta(i, est),
                            f"la misma consulta devuelve '{nombre(m, a)}' y luego "
                            f"'{nombre(m, b)}' (Δt=0)"))

    # ---- 4: almas imposibles ---------------------------------------------
    for almas in ALMAS_IMPOSIBLES:
        revisado[4] += 1
        est = {
            "t": 1200.0,
            "yo": {"heroe": "Abrams", "almas": almas, "items": []},
            "aliados": [{"heroe": "Kelvin", "almas": 3000}],
            "enemigos": [{"heroe": "Haze", "almas": 3000},
                         {"heroe": "Lash", "almas": 2800}],
            "confianza": 1.0,
        }
        r, ms = medir(m, est)
        latencias.append(ms)
        eco = r.get("economia") or {}
        caso = f"almas={almas} t=1200s"
        problemas = []
        for campo, valor in (("salida.almas", r.get("almas")),
                             ("economia.mias", eco.get("mias"))):
            if valor is not None and not (0 <= valor <= ALMAS_MAX):
                problemas.append(f"{campo}={valor} se propaga sin clamar")
        sano = min(max(almas, 0), ALMAS_MAX)
        caros = [x for x in (r.get("recomendaciones") or [])
                 if x["costo"] > sano
                 and not (x.get("accion") == "AHORRAR" and (x.get("faltan") or 0) > 0)]
        if caros:
            problemas.append(
                f"recomienda {[(x['nombre'], x['costo']) for x in caros]} "
                f"por encima del máximo sano {ALMAS_MAX}")
        # la decisión tiene que ser la misma que con el valor clamado
        clampado = dict(est)
        clampado["yo"] = dict(est["yo"], almas=sano)
        rc, ms = medir(m, clampado)
        latencias.append(ms)
        if _firma(r) != _firma(rc):
            problemas.append(f"decide distinto que con el valor clamado ({sano} almas)")
        if problemas:
            viol[4].append((caso, " · ".join(problemas)))

    # ---- 5: razones no vacías --------------------------------------------
    for i, (est, r) in enumerate(zip(estados, resultados)):
        for x in r.get("recomendaciones") or []:
            revisado[5] += 1
            if not [z for z in (x.get("razones") or []) if str(z).strip()]:
                viol[5].append((etiqueta(i, est),
                                f"'{x['nombre']}' ({x['id']}) sale sin razones "
                                f"(score={x['score']}, residual={x['residual']})"))
        revisado[5] += 1
        if not str((r.get("estado") or {}).get("motivo") or "").strip():
            viol[5].append((etiqueta(i, est), "el estado táctico no trae motivo"))
        if r.get("venta"):
            revisado[5] += 1
            if not str(r["venta"].get("motivo") or "").strip():
                viol[5].append((etiqueta(i, est), "la venta sugerida no trae motivo"))

    # ---- 6: latencia ------------------------------------------------------
    media = sum(latencias) / len(latencias) if latencias else 0.0
    if media >= LATENCIA_MAX_MS:
        viol[6].append((f"{len(latencias)} consultas",
                        f"media {media:.2f} ms >= {LATENCIA_MAX_MS:.0f} ms"))
    maxima = max(latencias) if latencias else 0.0

    # ---- resumen ----------------------------------------------------------
    print("=" * 74)
    print(f"INVARIANTES DEL MOTOR · {len(estados)} estados sintéticos · "
          f"{len(m.conoc['items'])} ítems de conocimiento")
    print(f"tiempo 0–{max(e['t'] for e in estados):.0f}s · almas "
          + ", ".join(f"{v}×{sum(1 for e in estados if e['yo']['almas'] == v)}"
                      for v in ALMAS_VALIDAS)
          + f" · slots llenos: {sum(1 for e in estados if len(e['yo']['items']) >= 12)}"
          f" · vacíos: {sum(1 for e in estados if not e['yo']['items'])}")
    print("=" * 74)
    total = 0
    for k in sorted(INVARIANTES):
        v = viol[k]
        total += len(v)
        estado = "OK   " if not v else "FALLA"
        extra = f"media {media:.2f} ms" if k == 6 else f"{revisado[k]} casos"
        print(f"[{k}] {INVARIANTES[k]:<44} {estado}  {len(v):>3} viol. · {extra}")
        for caso, detalle in v[:3]:
            print(f"      · {caso}: {detalle}")
        if len(v) > 3:
            print(f"      · ... y {len(v) - 3} más")

    if total:
        print("-" * 74)
        print("VIOLACIONES REALES DEL MOTOR (no se corrigen aquí: las decide el")
        print("ingeniero principal). Detalle completo en informes/qa2-violaciones.md")
        for k in sorted(INVARIANTES):
            if not viol[k]:
                continue
            causas = {
                3: "la ventana de apertura (t < 600 s) y `fase_flujo` cambian el "
                   "conjunto de candidatos de golpe al cruzar el minuto 10 "
                   "(en el panel lo tapa `Estabilizador`, pero el motor sí cambia)",
                2: "`_es_mejora_de()` siempre devuelve False y `candidatos()` no "
                   "consulta el árbol de componentes: recomienda el tier inferior "
                   "de un ítem ya comprado",
                4: "`validar()` detecta el rango pero no clama: el valor imposible "
                   "llega a economía, estado táctico y recomendaciones",
            }
            if k in causas:
                print(f"  [{k}] causa probable: {causas[k]}")

    verdes = sum(1 for k in INVARIANTES if not viol[k])
    print("-" * 74)
    print(f"Invariantes en verde: {verdes}/6 · violaciones: {total}")
    print(f"Tiempo: {time.perf_counter() - t_arranque:.2f} s · {len(latencias)} consultas "
          f"· media {media:.2f} ms · máx {maxima:.1f} ms")
    if total:
        ruta = escribir_informe(viol, estados, media, maxima)
        print(f"Informe: {ruta}")
    else:
        print("Sin violaciones: nada que documentar.")
    print(f"EXIT {1 if total else 0}")
    return 1 if total else 0


# --------------------------------------------------------------------------
# informe para el ingeniero principal (solo si hay violaciones)
# --------------------------------------------------------------------------
def escribir_informe(viol, estados, media, maxima):
    ruta = os.path.join(BASE, "informes", "qa2-violaciones.md")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)

    causas = {
        1: ("`candidatos()` filtra `if costo > almas` antes de puntuar, así que el "
            "coste nunca supera las almas del estado. Si esta invariante falla, "
            "revisar el camino de `sugerir_venta()` (`coach/motor.py:282`)."),
        2: ("`_es_mejora_de()` (`coach/motor.py:75-78`) siempre devuelve False y "
            "`candidatos()` (`coach/motor.py:160-161`) solo descarta "
            "`iid in poseidos`. Nadie consulta `component_items` de "
            "`data/items.json`, así que el tier inferior de un ítem ya comprado "
            "sigue siendo candidato."),
        3: ("`es_apertura = estado.t < 600 and bool(apertura)` "
            "(`coach/motor.py:158`) y `fase_flujo()` (`coach/motor.py:127-140`) "
            "cambian el conjunto de candidatos de golpe en las fronteras de "
            "600 s: dos consultas separadas por <10 s de partida pueden caer a "
            "lados distintos. No hay histéresis ni memoria entre consultas "
            "(`recomendar()` es pura), así que nada estabiliza el cambio."),
        4: ("`validar()` (`coach/estado.py:87-88`) detecta el rango pero solo "
            "devuelve el problema; `Motor.analizar_dict()` "
            "(`coach/motor_api.py:24-27`) lo anota y baja `confianza`, sin "
            "clampar. `candidatos()` (`coach/motor.py:150`) y `recomendar()` "
            "(`coach/motor.py:310`) usan `estado.yo.almas or 0` y deciden con el "
            "valor imposible; `economia()` (`coach/motor.py:34-44`) lo usa para "
            "el delta y el estado FARM/PELEAR."),
        5: ("Una recomendación sale sin razones cuando el ítem no está en la fase "
            "actual (`info_fase is None`), su `lift_residual` no es positivo, no "
            "da counter, no hace pareja y su cadena es <= 0.15 "
            "(`coach/motor.py:214-225`)."),
        6: "Medición de pared con `time.perf_counter()` alrededor de `analizar_dict()`.",
    }
    # qué tapa ya la app y qué queda expuesto (leído de run.py / estabilizador.py)
    mitiga = {
        2: ("Ninguna: `Estabilizador` (`coach/estabilizador.py`) solo reordena o "
            "retiene la recomendación anterior; no valida el árbol de ítems."),
        3: ("Parcial: `run.py` envuelve el motor con `Estabilizador` y su bloque de "
            "quietud (`coach/estabilizador.py:68-73`) retiene la recomendación "
            "anterior durante 10 s reales si el nuevo `score` no supera al actual "
            "en +3.0. En el caso S09 (3.6 → 4.8) la retendría, así que el panel "
            "probablemente no parpadea; la violación sigue siendo del motor "
            "`recomendar()`, que es lo que se pidió probar."),
        4: ("Parcial: `Estabilizador.anomalias()` "
            "(`coach/estabilizador.py:45-46`) solo añade la nota 'almas negativas' "
            "y conserva la recomendación anterior. `salida['almas']` y el "
            "historial del panel (`run.py:244-248`) siguen recibiendo el valor "
            "imposible."),
    }

    lineas = [
        "# QA2 · violaciones de invariantes del motor de decisión",
        "",
        f"Generado por `tests/test_invariantes.py` · "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- Estados sintéticos: {len(estados)} (t 0–2700 s, almas "
        f"{', '.join(str(a) for a in ALMAS_VALIDAS)}, slots vacíos/parciales/llenos)",
        f"- Latencia media: {media:.2f} ms · máxima {maxima:.1f} ms",
        "- Versiones medidas (sha256/12): "
        + " · ".join(f"{n}={_sha(os.path.join(BASE, r))}" for n, r in (
            ("motor.py", "coach/motor.py"),
            ("motor_api.py", "coach/motor_api.py"),
            ("estado.py", "coach/estado.py"),
            ("catalogo.py", "coach/catalogo.py"),
            ("conocimiento.json", "data/conocimiento.json"),
            ("items.json", "data/items.json"))),
        "- Alcance: solo lectura de `coach/*` y `data/*`. No se modificó código.",
        "",
        "| Invariante | Violaciones |",
        "|---|---|",
    ]
    for k in sorted(INVARIANTES):
        if viol[k]:
            lineas.append(f"| {k}. {INVARIANTES[k]} | **{len(viol[k])}** |")
    lineas.append("")

    for k in sorted(INVARIANTES):
        if not viol[k]:
            continue
        n = len(viol[k])
        lineas += [f"## Invariante {k} · {INVARIANTES[k]}", "",
                   f"**{n} {'violación' if n == 1 else 'violaciones'}.**", ""]
        if k in causas:
            lineas += ["Causa probable (leída del código, sin tocar):", "",
                       f"> {causas[k]}", ""]
        if k in mitiga:
            lineas += ["Mitigación en la app:", "", f"> {mitiga[k]}", ""]
        lineas.append("Casos que las producen:")
        lineas.append("")
        for caso, detalle in viol[k][:40]:
            lineas.append(f"- `{caso}` → {detalle}")
        if len(viol[k]) > 40:
            lineas.append(f"- … y {len(viol[k]) - 40} casos más")
        lineas.append("")

    lineas += [
        "## Qué NO se tocó",
        "",
        "`coach/*.py`, `run.py` y el resto de `tests/` quedan intactos. El arreglo",
        "lo decide el ingeniero principal.",
        "",
    ]

    # estados exactos que reproducen cada caso (copiar y pegar en un script)
    por_etiqueta = {etiqueta(i, e): e for i, e in enumerate(estados)}
    usados = {}
    for k in sorted(viol):
        for caso, _ in viol[k]:
            if caso in por_etiqueta:
                usados.setdefault(caso, por_etiqueta[caso])
    if usados:
        lineas += ["## Estados que reproducen", "",
                   "Cada estado se pasa tal cual a `Motor().analizar_dict(...)`.", ""]
        for caso, est in usados.items():
            lineas += [f"### {caso}", "", "```json",
                       json.dumps(est, ensure_ascii=False, indent=2), "```", ""]

    if viol[4]:
        lineas += ["## Plantilla de la invariante 4", "", "```python",
                   "m.analizar_dict({'t': 1200, 'yo': {'heroe': 'Abrams',",
                   "                'almas': -1000,  # probar -1, -500, -1000, 200001, 1e9",
                   "                'items': []},",
                   "               'aliados': [{'heroe': 'Kelvin', 'almas': 3000}],",
                   "               'enemigos': [{'heroe': 'Haze', 'almas': 3000},",
                   "                            {'heroe': 'Lash', 'almas': 2800}]})",
                   "```", ""]
    with open(ruta, "w") as f:
        f.write("\n".join(lineas))
    return ruta


if __name__ == "__main__":
    sys.exit(main())


def test_suite():
    """Entrada para `pytest -q`.

    Las suites están escritas como scripts con `main()` que devuelve el número de
    fallos. Este envoltorio las expone a pytest sin cambiar su comportamiento
    (siguen corriendo también con `python3 tests/<archivo>.py`).
    """
    assert main() == 0
