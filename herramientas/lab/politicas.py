"""G4 · ¿la política del motor v2 vale más que comprar lo que compra la gente?

Qué mide. Se entrena con el 60 % de las partidas (corte temporal) y se **evalúa** en el
20 % de test con la nuisance del entrenamiento: m̂ y ê se ajustan en train y se aplican a
filas que el modelo nunca vio. Ese detalle es todo: la primera versión ajustaba la
nuisance en test y el resultado salía inflado (modelo 0.65 contra la popularidad, cuando
con la nuisance bien aplicada la diferencia es de centésimas).

    V(π) = media_i m̂(π(x_i))  +  [ Σ_i 1{a_i=π}/ê(a_i) (y_i − m̂(π)) ] / [ Σ_i 1{a_i=π}/ê(a_i) ]

El segundo término va **autonormalizado** (SNIPS) y con los pesos recortados: sin eso el
valor se sale de [0, 1] y el intervalo que se publique describe a un estimador que no
existe.

Las políticas:

    observada     lo que compró el jugador (su valor es, por construcción, el winrate)
    popularidad   el ítem más comprado del estrato entre los factibles
    modelo        argmax de m̂ entre los factibles
    modelo_2      modelo con una compra de lookahead de verdad: la continuación de cada
                  candidato es el mejor ítem DISTINTO de él, no una constante

Límites declarados antes de mirar el número:

- Solo se evalúa sobre el **shortlist** (acciones con soporte). Una recomendación fuera
  del shortlist no se puede evaluar con estos datos y se cuenta como «sin soporte», no
  como acierto.
- La factibilidad usa `coste ≤ net_worth` como cota holgada de oro, excluye lo que ya se
  lleva puesto y los componentes ya superados.
- El bootstrap remuestrea **partidas**.
- Esto no prueba causalidad (falta MMR): mide si, con el supuesto de ignorabilidad que
  sostiene todo el artefacto, la política nueva se asocia a mejores resultados.

Uso:
    python3 herramientas/lab/politicas.py --partidas-test 3000
    python3 herramientas/lab/politicas.py --replicacion
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import corpus, estimador  # noqa: E402

GAMMA = 0.35
PESO_MAX = 20.0          # recorte del peso 1/ê: sin esto el DR se sale de [0, 1]
E_MIN = 0.02


# --------------------------------------------------------------------- utilidades
def _ids_partida_ordenados(datos, ruta_db=corpus.RUTA_DB):
    """Partidas ordenadas por fecha real (start_time de `partidas_api`)."""
    import sqlite3
    con = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True)
    try:
        filas = con.execute("SELECT match_id, start_time FROM partidas_api").fetchall()
    finally:
        con.close()
    fecha = {int(m): str(f or "") for m, f in filas}
    unicas = np.unique(datos["match"])
    return np.array(sorted(unicas, key=lambda m: (fecha.get(int(m), ""), int(m))))


def _cortes(partidas, fraccion=(0.6, 0.8)):
    """Cortes temporales por partida; `partidas` ya viene ordenada por fecha."""
    n = len(partidas)
    a, b = int(n * fraccion[0]), int(n * fraccion[1])
    return partidas[:a], partidas[a:b], partidas[b:]


def _subconjunto(datos, ids):
    sel = np.isin(datos["match"], ids)
    n = len(datos["match"])
    return {k: (v[sel] if isinstance(v, np.ndarray) and len(v) == n else v)
            for k, v in datos.items()}


def _clave_celda(franja, nw, n_items, nw_rel=None):
    """Clave de celda de propensión, calculable igual en train y en test.

    Lleva la cubeta de riqueza relativa (`estimador.cubeta_riqueza`) para que la
    replicación fuera de muestra mida el MISMO diseño que el artefacto. Sin `nw_rel`
    —el sintético— la cubeta vale 0 y la clave es la de antes.
    """
    nw_b = np.clip(np.asarray(nw).astype(np.int64) // 4000, 0, 5)
    inv_b = np.clip(np.asarray(n_items).astype(np.int64) // 4, 0, 2)
    rr_b = (estimador.cubeta_riqueza({"item": np.asarray(franja), "nw_rel": nw_rel})
            if nw_rel is not None
            else np.zeros(np.asarray(franja).shape, dtype=np.int64))
    return (np.asarray(franja).astype(np.int64) * 1000 + nw_b * 100 + rr_b * 10
            + inv_b).astype(np.int64)


def _poseidos(datos, corto_global):
    """Máscara (filas × acciones) de lo que el jugador YA lleva puesto.

    El motor real prohíbe comprar dos veces el mismo ítem; una política que lo haga no
    es la política de la app. Se reconstruye con el mismo barrido del inventario.
    """
    n = len(datos["t"])
    k = len(corto_global)
    pos = {int(item): j for j, item in enumerate(corto_global)}
    mascara = np.zeros((n, k), dtype=bool)
    grupo_previo = None
    poseidos = []
    for i in range(n):
        clave = (int(datos["match"][i]), int(datos["slot"][i]))
        if clave != grupo_previo:
            grupo_previo = clave
            poseidos = []
        t = float(datos["t"][i])
        # Lo vendido antes de este instante deja de estar puesto.
        poseidos = [p for p in poseidos if not (p[1] and p[1] <= t)]
        for item, _vend in poseidos:
            j = pos.get(int(item))
            if j is not None:
                mascara[i, j] = True
        poseidos.append((int(datos["item"][i]), float(datos["vendido_t"][i])))
    return mascara


# ------------------------------------------------------------------- entrenamiento
def entrenar(datos, cat, corto_global=None):
    """Ajusta ê (conteo suavizado) y m̂ (logístico) y devuelve el modelo congelado."""
    fr = corpus.franja(datos["t"])
    if corto_global is None:
        corto = corpus.shortlist(datos)
        corto_global = sorted({i for e in corto for i in corto[e]})
    pos = {item: j for j, item in enumerate(corto_global)}
    accion_idx = np.full(len(datos["item"]), -1, dtype=np.int16)
    dentro = np.isin(datos["item"], corto_global)
    accion_idx[dentro] = [pos[int(i)] for i in datos["item"][dentro]]
    if not np.all(dentro):
        n_todas = len(datos["item"])
        datos = {k: (v[dentro] if isinstance(v, np.ndarray) and len(v) == n_todas
                     else v) for k, v in datos.items()}
        fr = fr[dentro]
        accion_idx = accion_idx[dentro]

    claves = _clave_celda(fr, datos["nw"], datos["n_items"], datos.get("nw_rel"))
    unicas, inversa = np.unique(claves, return_inverse=True)
    k = len(corto_global)
    pi_base = np.bincount(accion_idx[accion_idx >= 0], minlength=k).astype(np.float64)
    pi = (pi_base + 1.0) / (pi_base.sum() + k)
    tabla = np.zeros((len(unicas), k), dtype=np.float64)
    np.add.at(tabla, (inversa[accion_idx >= 0], accion_idx[accion_idx >= 0]), 1.0)
    total = tabla.sum(axis=1, keepdims=True)
    suave = (tabla + estimador.ALFA_DIRICHLET * pi[None, :]) / (
        total + estimador.ALFA_DIRICHLET)

    base = estimador._base(datos)
    estaticas = estimador._accion(cat, [datos["ids"][i] for i in corto_global])
    acc = np.hstack([estaticas, np.eye(k, dtype=np.float32)])
    validas = accion_idx >= 0
    Xobs = np.hstack([base, acc[accion_idx.clip(0)]])
    beta = estimador.ajustar_logistico(Xobs[validas], datos["y"][validas])
    # Orden de popularidad por franja calculado SOLO con train. Calcularlo con el test
    # es ajustar el baseline en el conjunto de evaluación: infla la ventaja del modelo.
    orden_popular = {}
    for e in (0, 1, 2):
        sel = (fr == e) & (accion_idx >= 0)
        cuenta = (np.bincount(accion_idx[sel], minlength=k) if np.any(sel)
                  else np.zeros(k))
        orden_popular[e] = [int(x) for x in np.argsort(-cuenta)]
    return {"corto_global": corto_global, "beta": beta, "acc": acc,
            "claves": unicas, "suave": suave, "pi": pi, "cat": cat,
            "ids": datos["ids"], "orden_popular": orden_popular}


def aplicar(modelo, datos):
    """ê y m̂ del modelo aplicados a filas nuevas. Sin reajustar nada."""
    k = len(modelo["corto_global"])
    pos = {item: j for j, item in enumerate(modelo["corto_global"])}
    accion_idx = np.full(len(datos["item"]), -1, dtype=np.int16)
    dentro = np.isin(datos["item"], modelo["corto_global"])
    accion_idx[dentro] = [pos[int(i)] for i in datos["item"][dentro]]

    fr = corpus.franja(datos["t"])
    claves = _clave_celda(fr, datos["nw"], datos["n_items"], datos.get("nw_rel"))
    # La búsqueda es POR VALOR sobre las claves de train: `np.unique` sobre test
    # re-rankeaba las celdas y todo el ê salía mal (62 236 de 62 236 filas).
    idx = np.searchsorted(modelo["claves"], claves)
    idx_clip = np.clip(idx, 0, max(0, len(modelo["claves"]) - 1))
    dentro_celda = (idx < len(modelo["claves"])) & (
        modelo["claves"][idx_clip] == claves)
    e_hat = np.tile(modelo["pi"], (len(claves), 1))
    if len(modelo["claves"]):
        e_hat[dentro_celda] = modelo["suave"][idx_clip[dentro_celda]]
    e_hat = np.clip(e_hat, E_MIN, 0.98)

    base = estimador._base(datos)
    M = np.empty((len(datos["item"]), k), dtype=np.float32)
    for a in range(k):
        M[:, a] = estimador.predecir(modelo["beta"], np.hstack([
            base, np.broadcast_to(modelo["acc"][a],
                                  (len(base), len(modelo["acc"][a])))]))
    return {"datos": datos, "fr": fr, "accion_idx": accion_idx, "e_hat": e_hat,
            "M": M, "corto_global": modelo["corto_global"], "cat": modelo["cat"],
            "modelo": modelo, "cobertura_celdas": float(np.mean(dentro_celda))}


# --------------------------------------------------------------------- factibles
def _factibles(ctx):
    """Máscara (filas × acciones): pagable y no poseído."""
    datos = ctx["datos"]
    modelo = ctx["modelo"]
    cat = modelo["cat"]
    ids = modelo["corto_global"]
    n, k = ctx["M"].shape
    ok = np.ones((n, k), dtype=bool)
    for a in range(k):
        info = cat[modelo["ids"][ids[a]]]
        ok[:, a] &= datos["nw"] >= info["coste"]
    ok &= ~_poseidos(datos, ids)
    return ok


# ---------------------------------------------------------------------- políticas
def _politica_modelo(ctx, lookahead=False):
    """argmax de m̂ entre los factibles; con lookahead, la mejor compra siguiente.

    Trampa que hay que evitar: si la continuación es «el mejor ítem distinto de `a`»,
    el término es monótono y NUNCA cambia el argmax (la ventaja del primero es
    (1−γ)(m₁−m₂) ≥ 0). El lookahead de verdad depende del estado que deja la compra:
    al pagar `a` queda menos oro y eso puede impedir la continuación que hacía buena
    a `a`. Si no cabe ninguna continuación, el término es neutro (0.5).
    """
    M = ctx["M"]
    ok = _factibles(ctx)
    util = M.astype(np.float64).copy()
    if lookahead and M.shape[1] > 1:
        modelo = ctx["modelo"]
        cat = modelo["cat"]
        ids = modelo["corto_global"]
        costo = np.array([cat[modelo["ids"][i]]["coste"] for i in ids], dtype=np.float64)
        nw = ctx["datos"]["nw"].astype(np.float64)
        k = M.shape[1]
        mejor = M.astype(np.float64)
        cont = np.full_like(mejor, 0.5)
        for a in range(k):
            restante = nw - costo[a]
            cabe = (costo[None, :] <= restante[:, None]) & ok
            cabe[:, a] = False                       # no se compra dos veces lo mismo
            valores = np.where(cabe, M, -np.inf)
            m = valores.max(axis=1)
            m[~np.isfinite(m)] = 0.5
            cont[:, a] = m
        util = M + GAMMA * (cont - 0.5)
    util = np.where(ok, util, -1e9)
    salida = np.argmax(util, axis=1)
    # Sin ninguna acción factible no hay política: devolver el índice 0 recomendaba
    # Juggernaut (6 400) en estados de 730 de patrimonio. Se marca -1 y no cuenta.
    salida[~ok.any(axis=1)] = -1
    return salida, ok


def _politica_popularidad(ctx):
    """El ítem más comprado de su franja, si es factible; si no, el siguiente."""
    fr = ctx["fr"]
    k = ctx["M"].shape[1]
    ok = _factibles(ctx)
    orden_por_franja = (ctx["modelo"].get("orden_popular") or {})
    if not orden_por_franja:                      # compatibilidad con dobles de prueba
        accion = ctx["accion_idx"]
        for e in (0, 1, 2):
            sel = (fr == e) & (accion >= 0)
            cuenta = np.bincount(accion[sel], minlength=k) if np.any(sel) else np.zeros(k)
            orden_por_franja[e] = [int(x) for x in np.argsort(-cuenta)]
    salida = np.zeros(len(fr), dtype=np.int64)
    for i in range(len(fr)):
        elegido = int(orden_por_franja[int(fr[i])][0])
        for cand in orden_por_franja[int(fr[i])]:
            if ok[i, cand]:
                elegido = int(cand)
                break
        salida[i] = elegido
    return salida


# ------------------------------------------------------------------------- valor
def _valor(ctx, accion_pol, pesos=None):
    """Valor SNIPS de una política: media de m̂ + corrección autonormalizada."""
    datos = ctx["datos"]
    M = ctx["M"]
    e_hat = ctx["e_hat"]
    y = datos["y"].astype(np.float64)
    n = len(y)
    w = np.ones(n) if pesos is None else np.asarray(pesos, dtype=np.float64)
    obs = ctx["accion_idx"]
    filas = np.arange(n)
    valido = (accion_pol >= 0) & (obs >= 0)
    if not np.any(valido):
        return 0.0, 0.0, 0.0
    ape = np.clip(accion_pol, 0, M.shape[1] - 1)
    m_pol = M[filas, ape]
    e_obs = e_hat[filas, np.clip(obs, 0, M.shape[1] - 1)]
    coincide = (accion_pol == obs) & valido
    peso = np.where(coincide, np.minimum(1.0 / np.maximum(e_obs, E_MIN), PESO_MAX), 0.0)
    ww = w * peso
    denominador = ww[valido].sum()
    correccion = (ww[valido] @ (y[valido] - m_pol[valido])) / max(1e-9, denominador)
    base = (w[valido] @ m_pol[valido]) / max(1e-9, w[valido].sum())
    valor = float(base + correccion)
    # ESS sobre los pesos de la corrección: cuántas observaciones efectivas la sostienen.
    wp = peso[coincide]
    ess = float((wp.sum() ** 2) / max(1e-9, (wp ** 2).sum())) if wp.size else 0.0
    # Cobertura se mide sobre TODAS las filas, no sobre las que ya pasaron el filtro.
    cobertura = float(np.mean(accion_pol >= 0))
    return valor, ess, cobertura


# ---------------------------------------------------------------------- evaluación
def evaluar(partidas_test=4000, semilla=11, verbose=True):
    t0 = time.perf_counter()
    cat = corpus.catalogo()
    datos = corpus.con_inventario(corpus.cargar(), cat)
    idx_train, idx_val, idx_test = _cortes(_ids_partida_ordenados(datos))

    train = _subconjunto(datos, idx_train)
    modelo = entrenar(train, cat)

    rng = np.random.default_rng(semilla)
    partidas = list(int(x) for x in idx_test)
    if len(partidas) > partidas_test:
        partidas = list(rng.choice(partidas, size=partidas_test, replace=False))
    test = _subconjunto(datos, partidas)
    ctx = aplicar(modelo, test)
    if verbose:
        print(f"test: {len(partidas):,} partidas · {len(test['t']):,} compras · "
              f"{ctx['cobertura_celdas']:.0%} de celdas vistas · "
              f"{time.perf_counter()-t0:.1f} s", file=sys.stderr)

    pol_modelo, _ = _politica_modelo(ctx, lookahead=False)
    pol_modelo2, _ = _politica_modelo(ctx, lookahead=True)
    pol_popular = _politica_popularidad(ctx)
    pol_observada = ctx["accion_idx"].copy()

    politicas = {"observada": pol_observada, "popularidad": pol_popular,
                 "modelo": pol_modelo, "modelo_lookahead": pol_modelo2}
    resultados = {}
    for nombre, accion in politicas.items():
        valor, ess, cobertura = _valor(ctx, accion)
        resultados[nombre] = {"valor": round(valor, 4), "ess": round(ess, 1),
                              "cobertura": round(cobertura, 3)}

    # El lookahead se reporta como diagnóstico: aquí puede no cambiar nada, y decirlo
    # es parte del resultado (con ítems de ≤ 6 400 y 20-30 k de patrimonio, pagar uno
    # caro casi nunca impide la continuación).
    difieren_lookahead = int(np.sum(pol_modelo != pol_modelo2))

    partidas_arr, indice = np.unique(ctx["datos"]["match"], return_inverse=True)
    n_part = len(partidas_arr)
    difs = []
    for _ in range(200):
        pesos = rng.multinomial(n_part, np.full(n_part, 1.0 / n_part))[indice]
        a = _valor(ctx, pol_modelo, pesos)[0]
        b = _valor(ctx, pol_popular, pesos)[0]
        difs.append(a - b)
    difs = np.asarray(difs)
    return {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "partidas_train": int(len(idx_train)),
        "partidas_validacion": int(len(idx_val)),
        "partidas_test": int(len(partidas)),
        "filas_test": int(len(test["t"])),
        "acciones": len(modelo["corto_global"]),
        "celdas_vistas_en_test": round(ctx["cobertura_celdas"], 3),
        "winrate_test": round(float(np.mean(test["y"])), 4),
        "politicas": resultados,
        "filas_que_cambia_el_lookahead": difieren_lookahead,
        "modelo_menos_popularidad": {
            "media": round(float(difs.mean()), 4),
            "ic90": [round(float(np.percentile(difs, 5)), 4),
                     round(float(np.percentile(difs, 95)), 4)],
            "p_mayor_que_cero": round(float((difs > 0).mean()), 3),
        },
        "aviso": ("Off-policy con soporte limitado al shortlist y supuesto de "
                  "ignorabilidad; la nuisance se ajusta en train y se aplica a test. "
                  "No prueba causalidad sin MMR."),
        "segundos": round(time.perf_counter() - t0, 1),
    }


# ------------------------------------------------------------------ replicación
def _tau_en(ctx, comparables=False):
    """τ̂ por ítem dentro del propio conjunto (solo filas del shortlist).

    Con `comparables=True` usa el mismo contrafactual restringido al tramo de precio
    que el artefacto: la réplica fuera de muestra tiene que medir el MISMO estimando.
    """
    validas = ctx["accion_idx"] >= 0
    n = len(validas)
    datos = {k: (v[validas] if isinstance(v, np.ndarray) and len(v) == n else v)
             for k, v in ctx["datos"].items()}
    M = ctx["M"][validas]
    M = np.asarray(M, dtype=np.float64)
    e_hat = ctx["e_hat"][validas]
    accion_idx = ctx["accion_idx"][validas]
    fr = ctx["fr"][validas]
    mu = estimador._mu_estratos(M, datos["y"], e_hat, accion_idx, fr)
    ids = ctx["corto_global"]
    modelo = ctx["modelo"]
    frec = np.zeros((3, len(ids)))
    n_ea = np.zeros_like(frec)
    for i in range(3):
        sel = fr == i
        if np.any(sel):
            cuenta = np.bincount(accion_idx[sel], minlength=len(ids))
            frec[i] = cuenta / max(1, cuenta.sum())
            n_ea[i] = cuenta
    n_a = n_ea.sum(axis=0)
    if comparables:
        tramo = estimador.tramos_precio(modelo["cat"],
                                        [modelo["ids"][i] for i in ids])
        tau = estimador._tau_comparables(mu, frec, tramo)
        tau_item = estimador._agregar_tau(tau, n_ea)
        return {modelo["ids"][ids[a]]: float(tau_item[a] * 100.0)
                for a in range(len(ids))
                if n_a[a] > 0 and np.isfinite(tau_item[a])}
    tau = estimador._tau(mu, frec)
    return {modelo["ids"][ids[a]]: float((n_ea[:, a] * tau[:, a]).sum() / n_a[a] * 100.0)
            for a in range(len(ids)) if n_a[a] > 0}


def replicacion(partidas_test=None, semilla=11, verbose=True, ids_items=None,
                riqueza=True, comparables=False):
    """¿El efecto estimado en train se repite en partidas que el modelo no vio?

    `ids_items` fija el conjunto de acciones a comparar: sin él se usa el shortlist de
    train, que puede no coincidir con el del artefacto (y entonces un ítem se queda sin
    marcar sin decirlo). `comparables=True` replica el estimando restringido al mismo
    tramo de precio; sin él, la réplica mediría otro número.
    """
    cat = corpus.catalogo()
    datos = corpus.con_inventario(corpus.cargar(), cat)
    if not riqueza:
        # Réplica del diseño anterior: sin la columna, `_clave_celda` y `_base` vuelven
        # a lo de antes. Existe para poder comparar antes/después con el mismo corte.
        datos = {k: v for k, v in datos.items()
                 if k not in ("nw_rel", "nw_med", "nw_pct", "nw_n")}
    idx_train, _, idx_test = _cortes(_ids_partida_ordenados(datos))
    train = _subconjunto(datos, idx_train)
    corto_global = None
    if ids_items:
        pos = {item: i for i, item in enumerate(datos["ids"])}
        corto_global = sorted({pos[i] for i in ids_items if i in pos})
    modelo = entrenar(train, cat, corto_global=corto_global)
    ctx_train = aplicar(modelo, train)
    test = _subconjunto(datos, idx_test)
    if partidas_test and len(idx_test) > partidas_test:
        rng = np.random.default_rng(semilla)
        test = _subconjunto(datos, rng.choice(idx_test, size=partidas_test,
                                              replace=False))
    ctx_test = aplicar(modelo, test)

    tau_train = _tau_en(ctx_train, comparables=comparables)
    tau_test = _tau_en(ctx_test, comparables=comparables)
    comunes = sorted(set(tau_train) & set(tau_test))
    if not comunes:
        return {"error": "sin acciones comunes"}
    x = np.array([tau_train[a] for a in comunes])
    y = np.array([tau_test[a] for a in comunes])

    def _rank(v):
        orden = v.argsort()
        r = np.empty_like(orden, dtype=float)
        r[orden] = np.arange(len(v), dtype=float)
        return r

    rho = float(np.corrcoef(_rank(x), _rank(y))[0, 1]) if len(x) > 2 else float("nan")
    por_item = {a: {"train_pp": round(float(tau_train[a]), 3),
                    "test_pp": round(float(tau_test[a]), 3),
                    "signo": bool((tau_train[a] > 0) == (tau_test[a] > 0))}
                for a in comunes}
    if verbose:
        print(f"replicación: {len(comunes)} acciones · "
              f"{ctx_test['cobertura_celdas']:.0%} celdas vistas", file=sys.stderr)
    return {
        "por_item": por_item,
        "acciones_comunes": len(comunes),
        "comparables": bool(comparables),
        "spearman_train_vs_test": round(rho, 3),
        "acuerdo_de_signo": round(float(np.mean(np.sign(x) == np.sign(y))), 3),
        "cobertura_celdas": round(ctx_test["cobertura_celdas"], 3),
        "tau_train_pp": {a: round(float(tau_train[a]), 2) for a in comunes},
        "tau_test_pp": {a: round(float(tau_test[a]), 2) for a in comunes},
    }


def main():
    ap = argparse.ArgumentParser(description="G4: valor de la política del motor v2")
    ap.add_argument("--partidas-test", type=int, default=4000)
    ap.add_argument("--semilla", type=int, default=11)
    ap.add_argument("--replicacion", action="store_true",
                    help="mide la replicación fuera de muestra")
    a = ap.parse_args()
    if a.replicacion:
        r = replicacion(a.partidas_test, a.semilla)
        print(json.dumps({k: v for k, v in r.items() if not k.startswith("tau_")},
                         indent=1, ensure_ascii=False))
    else:
        print(json.dumps(evaluar(a.partidas_test, a.semilla), indent=1,
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
