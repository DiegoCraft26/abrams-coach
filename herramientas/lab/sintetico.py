"""Corpus sintético con efecto conocido: la única forma de saber si el estimador miente.

Por qué existe. Un estimador puede devolver números bonitos y estar sesgado; con datos
reales no hay verdad contra la cual compararlo. Aquí se genera un corpus con el mismo
esquema que `lab.db` (partidas, compras, desenlace) donde el efecto de cada ítem **se
elige**, y se comprueba que el estimador lo recupera:

    Y = 1{ u + θ_a + ε > 0 },   u ~ N(0,1), ε ~ N(0,1),  a elegido según x

con lo que P(Y=1|a) = Φ(θ_a/√2) — verdad analítica, sin aproximación. El sesgo, la
cobertura del intervalo y los falsos positivos se miden contra ese número.

También se puede generar el caso **confundido** (la elección depende de `u`, la
habilidad no observada): no es una puerta de calidad, es la demostración de cuánto
duele lo que este corpus real no puede corregir.

Uso:
    python3 herramientas/lab/sintetico.py            # un corpus de ejemplo
    python3 herramientas/lab/validar.py --repeticiones 40
"""
from __future__ import annotations

import math

import numpy as np

# Ítems sintéticos: mismo esquema que `corpus.catalogo()`.
ITEMS = {}
for j in range(12):
    ITEMS[f"s{j}"] = {
        "nombre": f"Item {j}",
        "coste": [800, 1600, 3200, 6400][j % 4],
        "tier": (j % 4) + 1,
        "slot": ["weapon", "vitality", "spirit"][j % 3],
        "activo": j % 5 == 0,
    }


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def efecto_verdadero(theta, frecuencia):
    """τ(a) = Φ(θ_a/√2) − Σ_{a'≠a} p_a'/(1−p_a) · Φ(θ_a'/√2), en puntos porcentuales.

    Es EXACTAMENTE el estimando del estimador (contrafactual = la compra alternativa
    del shortlist, no «no comprar»). Si aquí se usara la media simple, la «verdad» y
    lo estimado no serían el mismo número y la validación mediría otra cosa.
    """
    prob = np.asarray([_phi(th / math.sqrt(2.0)) for th in theta])
    frec = np.asarray(frecuencia, dtype=float)
    tau = np.zeros_like(prob)
    for a in range(len(prob)):
        if frec[a] >= 0.999:
            continue
        pesos = frec / (1.0 - frec[a])
        pesos[a] = 0.0
        tau[a] = prob[a] - float(pesos @ prob)
    return tau * 100.0


def generar(n_partidas=8000, compras_por_partida=1, theta=None, semilla=11,
            confundido=False, ruido_inventario=0.0):
    """Genera un corpus con la forma de `lab.db` y devuelve (datos, verdad).

    `theta` es el vector de efectos por ítem en la escala probit. `confundido=True`
    hace que la elección dependa de la habilidad no observada `u` (lo que el corpus
    real no puede descartar).
    """
    rng = np.random.default_rng(semilla)
    n_items = len(ITEMS)
    if theta is None:
        theta = np.zeros(n_items)
        # Φ(0.071/√2) − 0.5 ≈ +2 pp contra la compra alternativa del shortlist.
        theta[1] = 0.071
        theta[4] = -0.071
    theta = np.asarray(theta, dtype=float)

    ids = list(ITEMS)
    filas_match, filas_slot, filas_orden, filas_t = [], [], [], []
    filas_item, filas_coste, filas_nw, filas_y = [], [], [], []
    frec = np.zeros(n_items)

    for m in range(n_partidas):
        u = rng.normal()
        # El ítem "objetivo" de la partida: el que fija el desenlace.
        # La elección depende de x (franja y riqueza) y, si `confundido`, de u.
        for k in range(compras_por_partida):
            t = float(rng.uniform(60, 2400))
            # La franja sale de `t` (dato observable), no de una variable oculta: si
            # la elección dependiera de algo que el estimador no ve, el experimento
            # mediría confusión no identificable, no el sesgo del estimador.
            franja_p = 0 if t < 900 else (1 if t < 1800 else 2)
            nw = int(rng.uniform(800, 30000))
            logits = rng.normal(size=n_items) * 0.4
            logits += 0.3 * (np.arange(n_items) % 3 == franja_p)
            logits += 0.8 * (np.arange(n_items) % 4) * (nw / 30000.0)
            if confundido and k == 3:
                logits += 1.6 * u           # la habilidad empuja la elección
            probabilidades = np.exp(logits - logits.max())
            probabilidades /= probabilidades.sum()
            a = int(rng.choice(n_items, p=probabilidades))
            filas_match.append(m)
            filas_slot.append(0)
            filas_orden.append(k + 1)
            filas_t.append(t)
            filas_item.append(a)
            filas_coste.append(ITEMS[ids[a]]["coste"])
            filas_nw.append(nw)
            # El desenlace lo fija la PRIMERA compra (con una compra por partida, esa).
            if k == 0:
                frec[a] += 1
                p = _phi(theta[a] / math.sqrt(2.0))
                filas_y.append(int(rng.random() < p))
            else:
                filas_y.append(0)           # se sobreescribe abajo
    # Una sola verdad por partida: se replica a todas sus filas para que el estimador
    # (que promedia por fila) vea exactamente el mismo desenlace.
    y_partida = {}
    for i, m in enumerate(filas_match):
        if filas_orden[i] == 1:
            y_partida[m] = filas_y[i]
    filas_y = [y_partida[m] for m in filas_match]

    datos = {
        "ids": ids,
        "match": np.asarray(filas_match, dtype=np.int64),
        "slot": np.asarray(filas_slot, dtype=np.int16),
        "orden": np.asarray(filas_orden, dtype=np.int16),
        "t": np.asarray(filas_t, dtype=np.float32),
        "item": np.asarray(filas_item, dtype=np.int32),
        "coste": np.asarray(filas_coste, dtype=np.int32),
        "nw": np.asarray(filas_nw, dtype=np.int64),
        "vendido_t": np.zeros(len(filas_match), dtype=np.float32),
        "y": np.asarray(filas_y, dtype=np.int8),
    }
    # Inventario sintético: cuenta simple de compras previas dentro de la partida.
    n = len(datos["t"])
    datos["n_items"] = np.zeros(n, dtype=np.int16)
    datos["inversion"] = np.zeros(n, dtype=np.int32)
    datos["n_activos"] = np.zeros(n, dtype=np.int16)
    previo = {}
    for i in range(n):
        m = int(datos["match"][i])
        acumulado = previo.get(m, [0, 0, 0])
        datos["n_items"][i], datos["inversion"][i], datos["n_activos"][i] = acumulado
        item = int(datos["item"][i])
        previo[m] = [acumulado[0] + 1, acumulado[1] + int(datos["coste"][i]),
                     acumulado[2] + (1 if ITEMS[ids[item]]["activo"] else 0)]

    frecuencia = frec / max(1.0, frec.sum())
    # La verdad se calcula con la frecuencia de cada franja, igual que el estimador.
    verdad = {
        "theta": {ids[j]: float(theta[j]) for j in range(n_items)},
        "efecto_pp": {ids[j]: float(efecto_verdadero(theta, frecuencia)[j])
                      for j in range(n_items)},
        "frecuencia": {ids[j]: float(frecuencia[j]) for j in range(n_items)},
    }
    # P(Y=1|a) verdadera por ítem, para que el validador calcule el MISMO estimando.
    verdad["prob"] = {ids[j]: float(_phi(theta[j] / math.sqrt(2.0)))
                      for j in range(n_items)}
    return datos, verdad


def catalogo():
    return {k: dict(v) for k, v in ITEMS.items()}


if __name__ == "__main__":
    import json
    datos, verdad = generar()
    print(json.dumps(verdad["efecto_pp"], indent=1, ensure_ascii=False))
    print(f"filas={len(datos['t']):,} partidas={len(set(datos['match'].tolist())):,} "
          f"wr={datos['y'].mean():.3f}")
