"""Corpus sintético con efecto conocido, en el MISMO formato que `demos_norm.csv.gz`.

Para qué. El estimador v3 decide con dos piezas que no se pueden auditar sobre datos
reales: (1) la reconstrucción del conjunto asequible y de la banda ±50 %, y (2) el AIPW
con el modelo de desenlace. Aquí se genera una tabla con las 27 columnas de la real, los
mismos estados (oro, franja, slot, héroe) y el mismo catálogo, donde el efecto de cada
ítem **se elige**. Si el estimador no recupera el signo de lo que se sembró, la maquinaria
está mal y ningún número real vale.

Diseño:

1. Se muestrean filas de la tabla real (los estados son los reales).
2. Cada fila es su propia jugador-partida (`match_id` único): una compra por partida. Así
   el desenlace no se replica entre compras y el efecto del ítem no se diluye.
3. El ítem se elige del menú asequible de ese estado con una política que imita a los
   jugadores de la muestra: sesgo fuerte a lo más caro que alcanza.
4. `Y ~ Bernoulli(p_a)` con `p_a = Φ(θ_a/√2)`; `θ_a` se siembra para seis ítems
   (+0,5 ×3 y −0,5 ×3) y 0 para el resto.
5. La verdad se calcula con el MISMO estimando y los MISMOS conjuntos S_i que usará el
   estimador: `τ(a) = media_{i: a} [p_a − media_{a'∈S_i} p_a']`. No es una aproximación.

Con `--confundido` la elección y el desenlace comparten una habilidad no observada: sirve
para medir cuánto duele lo que este diseño no puede corregir (no es una puerta de calidad).

Uso:
    python3 herramientas/lab/sintetico_v3.py --filas 16145 --semilla 11 \
        --salida /tmp/sint.csv.gz --verdad /tmp/sint_verdad.json
    python3 herramientas/lab/estimador_v3.py --tabla /tmp/sint.csv.gz \
        --verdad /tmp/sint_verdad.json --bootstrap 100 --salida /tmp/sint.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import sys

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import estimador_v3 as ev  # noqa: E402

COLUMNAS = ("match_id", "slot", "hero_id", "tick", "segundos", "segundos_fuente",
            "item_id", "item_nombre", "coste_catalogo", "oro_antes", "pagado",
            "descuento_componentes", "franja", "resultado", "heroes_en_partida",
            "slot_confianza", "n_asequibles", "n_alternativas", "n_alt_mismo_slot",
            "n_alt_50pct", "comprado_es_max", "rango_precio", "pago_observado",
            "pago_ambiguo", "grafo_componentes", "mediana_descuento",
            "pausas_conocidas")


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def generar(filas=16145, semilla=11, confundido=False, theta_items=None,
            verbose=True):
    """Devuelve (registros, verdad). `theta_items` es {item_id: θ} o None."""
    _, arr, _ = ev.cargar_tabla()
    cat, comp, comprables = ev.cargar_catalogo()
    menus = ev.construir_menus(arr, cat, comp, comprables, verbose=False)
    n_real = len(arr["item"])
    rng = np.random.default_rng(semilla)
    elegidas = rng.integers(0, n_real, size=filas)

    # Política de elección: sesgo a lo más caro que alcanza, con ruido logístico.
    beta_coste, beta_max = 2.2, 3.2
    nombre = {j: comprables[j] for j in range(len(comprables))}
    elegido = np.zeros(filas, dtype=np.int64)
    for k, i in enumerate(elegidas):
        ini, fin = menus["ini"][i], menus["ini"][i + 1]
        if fin <= ini:
            elegido[k] = -1
            continue
        acc = menus["acc"][ini:fin].astype(np.int64)
        # el sintético no tiene inventario: solo son elegibles los ítems que se pagan
        # completos con el oro disponible (si no, el menú que reconstruye el estimador
        # no los contendría y la fila quedaría fuera).
        alcanza = menus["coste_c"][acc] <= int(arr["oro"][i])
        if not np.any(alcanza):
            elegido[k] = -1
            continue
        acc = acc[alcanza]
        coste = menus["coste_c"][acc] / 6400.0
        tam = len(acc)
        es_max = (np.arange(tam) >= tam - 1).astype(float)
        v = beta_coste * coste + beta_max * es_max + 0.8 * rng.normal(size=tam)
        v -= v.max()
        p = np.exp(v)
        p /= p.sum()
        elegido[k] = acc[int(rng.choice(tam, p=p))]
    valido = elegido >= 0
    if verbose:
        print(f"elegidos: {int(valido.sum()):,}/{filas:,}", file=sys.stderr)

    # θ sembrado: seis ítems con efecto, el resto a cero.
    if theta_items is None:
        cuenta = np.bincount(elegido[valido], minlength=len(comprables))
        top = np.argsort(-cuenta)[:6]
        theta_items = {}
        for r, j in enumerate(top):
            theta_items[nombre[int(j)]] = 0.5 if r % 2 == 0 else -0.5
    theta = np.zeros(len(comprables))
    for j in range(len(comprables)):
        theta[j] = float(theta_items.get(nombre[j], 0.0))
    proba = np.asarray([_phi(t / math.sqrt(2.0)) for t in theta])

    # Habilidad no observada (solo en la variante confundida).
    u = rng.normal(size=filas) if confundido else np.zeros(filas)

    registros = []
    for k, i in enumerate(elegidas):
        if not valido[k]:
            continue
        j = int(elegido[k])
        iid = nombre[j]
        p = proba[j] + (0.12 * u[k] if confundido else 0.0)
        y = int(rng.random() < min(0.999, max(0.001, p)))
        registros.append({
            "match_id": str(900_000_000 + k),
            "slot": int(arr["slot"][i]),
            "hero_id": int(arr["hero"][i]),
            "tick": int(arr["tick"][i]),
            "segundos": float(arr["t"][i]),
            "segundos_fuente": "sintetico",
            "item_id": iid,
            "item_nombre": cat[iid].get("nombre"),
            "coste_catalogo": int(cat[iid]["costo"]),
            "oro_antes": int(arr["oro"][i]),
            "pagado": int(cat[iid]["costo"]),
            "descuento_componentes": 0,
            "franja": int(arr["franja"][i]),
            "resultado": "victoria" if y else "derrota",
            "heroes_en_partida": "",
            "slot_confianza": 1,
            "n_asequibles": int(menus["ini"][i + 1] - menus["ini"][i]),
            "n_alternativas": int(menus["ini"][i + 1] - menus["ini"][i]) - 1,
            "n_alt_mismo_slot": 0,
            "n_alt_50pct": 0,
            "comprado_es_max": 0,
            "rango_precio": 0,
            "pago_observado": 1,
            "pago_ambiguo": 0,
            "grafo_componentes": int(iid in comp),
            "mediana_descuento": 0.0,
            "pausas_conocidas": 1,
        })
    if verbose:
        print(f"filas sintéticas: {len(registros):,}", file=sys.stderr)
    return registros, {"theta": theta_items, "nombres": nombre,
                       "prob": {nombre[j]: float(proba[j])
                                for j in range(len(comprables))},
                       "confundido": bool(confundido)}


def verdad_empirica(ruta, verdad):
    """τ verdadero por ítem con el MISMO estimando y los MISMOS conjuntos S_i.

    Se recalcula el conjunto sobre la tabla sintética ya escrita (no sobre el estado
    original), para que la verdad hable exactamente de las filas que verá el estimador.
    """
    _, arr, _ = ev.cargar_tabla(ruta)
    cat, comp, comprables = ev.cargar_catalogo()
    menus = ev.construir_menus(arr, cat, comp, comprables, verbose=False)
    prob = verdad["prob"]
    p_items = np.asarray([prob.get(i, 0.5) for i in comprables])
    n = len(arr["item"])
    a_obs = np.full(n, -1, dtype=np.int64)
    ok = menus["elegido"] >= 0
    a_obs[ok] = menus["acc"][menus["elegido"][ok]]
    # media de p en el conjunto de comparación de cada fila
    media_s = np.zeros(n)
    cuenta = np.zeros(n)
    fila = menus["fila"]
    banda = menus["banda"]
    suma = np.bincount(fila[banda], weights=p_items[menus["acc"][banda]], minlength=n)
    cuenta = np.bincount(fila[banda], minlength=n)
    media_s = np.divide(suma, np.maximum(cuenta, 1), out=np.full(n, np.nan),
                        where=cuenta > 0)
    contraste = np.where(cuenta > 0, p_items[np.maximum(a_obs, 0)] - media_s, np.nan)
    uso = ok & np.isfinite(contraste)
    n_acc = np.bincount(a_obs[uso], minlength=len(comprables))
    s = np.bincount(a_obs[uso], weights=contraste[uso], minlength=len(comprables))
    tau = np.divide(s, n_acc, out=np.full(len(comprables), np.nan), where=n_acc > 0)
    items = {}
    for j, iid in enumerate(comprables):
        if n_acc[j] <= 0 or not np.isfinite(tau[j]):
            continue
        items[iid] = {"theta": float(verdad["theta"].get(iid, 0.0)),
                      "p": float(p_items[j]),
                      "tau_pp": round(float(tau[j]) * 100.0, 2),
                      "n": int(n_acc[j])}
    return {"items": items, "filas": int(uso.sum()),
            "confundido": verdad["confundido"]}


def comparar(doc_estimador, verdad):
    """Tabla estimado vs verdad para los ítems con muestra."""
    filas = []
    for iid, v in verdad["items"].items():
        e = doc_estimador["items"].get(iid)
        if not e:
            continue
        filas.append({
            "item": e["nombre"], "item_id": iid, "n": e["n"],
            "theta": v["theta"], "verdad_pp": v["tau_pp"],
            "estimado_pp": e["efecto_pp"], "ic90": e["ic90"],
            "sesgo_pp": round(e["efecto_pp"] - v["tau_pp"], 2),
            "signo_ok": bool(np.sign(e["efecto_pp"]) == np.sign(v["tau_pp"])),
            "cubre": bool(e["ic90"][0] <= v["tau_pp"] <= e["ic90"][1]),
        })
    filas.sort(key=lambda f: -abs(f["verdad_pp"]))
    con_efecto = [f for f in filas if abs(f["theta"]) > 1e-9]
    return {
        "items": filas,
        "resumen": {
            "items_comparables": len(filas),
            "items_con_efecto": len(con_efecto),
            "signo_ok": int(sum(f["signo_ok"] for f in con_efecto)),
            "cubre_ic90": int(sum(f["cubre"] for f in con_efecto)),
            "sesgo_medio_pp": (round(float(np.mean([f["sesgo_pp"] for f in con_efecto])), 2)
                               if con_efecto else None),
            "correlacion": (round(float(np.corrcoef(
                [f["verdad_pp"] for f in filas], [f["estimado_pp"] for f in filas])[0, 1]), 3)
                if len(filas) > 2 else None),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Corpus sintético v3")
    ap.add_argument("--filas", type=int, default=16145)
    ap.add_argument("--semilla", type=int, default=11)
    ap.add_argument("--salida", default="/tmp/sint.csv.gz")
    ap.add_argument("--verdad", default="/tmp/sint_verdad.json")
    ap.add_argument("--confundido", action="store_true")
    a = ap.parse_args(argv)
    registros, verdad = generar(a.filas, a.semilla, a.confundido)
    with gzip.open(a.salida, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        w.writerows(registros)
    v = verdad_empirica(a.salida, verdad)
    v["theta"] = {k: float(val) for k, val in verdad["theta"].items()}
    v["prob"] = verdad["prob"]
    with open(a.verdad, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"escrito {a.salida} ({len(registros)} filas) y {a.verdad}")
    print(json.dumps({k: v for k, v in sorted(
        v["items"].items(), key=lambda kv: -abs(kv[1]["tau_pp"]))[:8]},
        indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
