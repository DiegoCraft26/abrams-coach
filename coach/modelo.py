"""Modelo aprendido: en vez de pesos a mano, una regresión logística entrenada.

La etiqueta es si la partida se ganó. Cada fila es (estado antes de comprar, ítem comprado).
El modelo responde: dado este estado y este ítem, ¿cuánto sube la probabilidad de ganar?
"""
import json, math, os
import numpy as np

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(DIR, "data", "modelo.json")

NOMBRES = [
    "residual",        # valor del ítem por encima de su minuto de compra
    "counter",         # ventaja contra la composición enemiga
    "cadena",          # probabilidad de ser la compra siguiente
    "fase",            # cercanía al minuto típico de compra
    "flujo",           # winrate ajustado en la fase actual
    "precio",          # fracción de tus almas que consume
    "tier",            # nivel del ítem
    "muestra",         # log10 de las partidas que respaldan el ítem
]


def _slot_libre(estado, item_slot, cap, usados):
    return (cap.get(item_slot, 4) - usados.get(item_slot, 0)) / 4.0


def caracteristicas(estado, iid, d, conoc, cat, cfg, contexto):
    """Vector de rasgos de una decisión. `contexto` trae lo precalculado del estado."""
    residual = d["lift_residual"] * 100
    counter = contexto["counter"].get(iid, 0.0) * 100
    cadena = contexto["cadena"].get(iid, 0.0)
    t_rel = contexto["t_rel"]
    mc = d.get("min_compra")
    fase = -abs(t_rel - mc)/10.0 if mc is not None else -3.0
    flujo = contexto["flujo"].get(iid, 0.0)
    almas = max(1, estado.yo.almas or 1)
    precio = (d["costo"] or 0) / almas
    tier = float(d.get("tier") or 
                 0) / 5.0
    muestra = math.log10(max(1, d.get("n") or 1)) / 6.0
    return np.array([residual, counter, cadena, fase, flujo, precio, tier, muestra], dtype=float)


def entrenar(X, y, epocas=3000, lr=0.5, l2=1e-3):
    """Regresión logística por descenso de gradiente. Devuelve (pesos, media, desviación)."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    n, k = Z.shape
    w = np.zeros(k)
    b = 0.0
    for _ in range(epocas):
        p = 1.0 / (1.0 + np.exp(-(Z @ w + b)))
        g = Z.T @ (p - y) / n + l2 * w
        w -= lr * g
        b -= lr * float((p - y).mean())
    return {"w": w.tolist(), "b": float(b), "mu": mu.tolist(), "sd": sd.tolist(), "nombres": NOMBRES}


def predecir(modelo, x):
    mu = np.array(modelo["mu"]); sd = np.array(modelo["sd"])
    z = (np.array(x, dtype=float) - mu) / sd
    return 1.0 / (1.0 + math.exp(-(float(z @ np.array(modelo["w"])) + modelo["b"])))


def auc(y, p):
    """Área bajo la curva ROC, sin sklearn."""
    y = np.asarray(y); p = np.asarray(p)
    orden = np.argsort(p)
    y = y[orden]
    pos = y.sum(); neg = len(y) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rangos = np.arange(1, len(y)+1)
    suma_pos = rangos[y == 1].sum()
    return (suma_pos - pos*(pos+1)/2) / (pos*neg)


def guardar(modelo):
    json.dump(modelo, open(RUTA, "w"), indent=1)


def cargar():
    if os.path.exists(RUTA):
        return json.load(open(RUTA))
    return None
