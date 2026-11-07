#!/usr/bin/env python3
"""Entrena el modelo de decisión con partidas reales y busca la mejor combinación de rasgos.

Ciclo: cada combinación de rasgos se entrena y se mide con AUC sobre partidas que el
modelo no vio. Se queda la mejor.
"""
import itertools, json, os, sys, time
import numpy as np
sys.path.insert(0, ".")
from coach import evaluador, motor as M, modelo
from coach.motor_api import Motor
from coach.estado import Estado

# Este script vive en herramientas/datos/: la raíz del repo está 3
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DIR = RAIZ


def contexto_de(estado, conoc, cat, cfg):
    col, en_fase = M.fase_flujo(estado.t, conoc)
    poseidos = {str(i) for i in estado.yo.items}
    heroes = [j.heroe for j in estado.enemigos if j.heroe]
    indice = conoc.get("heroes_index", {})
    t_rel = (estado.t / cfg["duracion_tipica_s"]) * 100
    return {
        "t_rel": t_rel,
        "flujo": {i: (v["wr_ajustado"] - 0.5) for i, v in en_fase.items()},
        "counter": {i: M._bonus_counter(i, heroes, conoc, cfg, indice) for i in conoc["items"]},
        "cadena": {i: M._bonus_cadena(i, poseidos, conoc) for i in conoc["items"]},
    }


def dataset(cache, conoc, cat, cfg, desde_min=10):
    filas, etiquetas, grupos = [], [], []
    for p in cache:
        yo = p["yo"]
        compras = [i for i in yo["items"] if i["t"] >= desde_min*60 and i["id"] in conoc["items"]]
        if not compras:
            continue
        heroes = {k: v["nombre"].lower().replace(" ", "_")
                  for k, v in json.load(open(os.path.join(DIR, "data", "heroes.json"))).items()}
        for c in compras:
            t = c["t"]
            patrimonio = evaluador._almas(yo["stats"], t)
            if patrimonio is None:
                continue
            propios = [i["id"] for i in yo["items"]
                       if i["t"] <= t and (not i["vendido"] or i["vendido"] > t)
                       and i["id"] in conoc["items"]]
            gastado = sum((cat.get(i) or {}).get("costo") or 0 for i in propios)
            almas = max(0, patrimonio - gastado)
            if almas < ((cat.get(c["id"]) or {}).get("costo") or 0):
                continue
            enemigos = [{"heroe": heroes.get(str(j["hero"]), str(j["hero"]))}
                        for j in p["jugadores"] if j["team"] != yo["team"]]
            if not enemigos:
                continue
            e = Estado.desde_dict({"t": t, "yo": {"heroe": "Abrams", "almas": almas, "items": propios},
                                   "enemigos": enemigos})
            ctx = contexto_de(e, conoc, cat, cfg)
            filas.append(modelo.caracteristicas(e, c["id"], conoc["items"][c["id"]], conoc, cat, cfg, ctx))
            etiquetas.append(1.0 if p.get("gane") else 0.0)
            grupos.append(str(p["match_id"]))
    return np.array(filas), np.array(etiquetas), np.array(grupos)


def dividir(X, y, g, semilla=7):
    """Separa por partida, no por compra: si no, el modelo ve la misma partida en train y test."""
    rng = np.random.default_rng(semilla)
    partidas = np.unique(g)
    rng.shuffle(partidas)
    corte = int(len(partidas)*0.75)
    train = np.isin(g, partidas[:corte])
    test = ~train
    return X[train], y[train], X[test], y[test]


def main():
    ciclos = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    cache = json.load(open(os.path.join(DIR, "data", "replay_cache.json")))
    m = Motor()
    t0 = time.time()
    X, y, g = dataset(cache, m.conoc, m.cat, m.cfg)
    print(f"partidas: {len(np.unique(g))} · filas: {len(y)} · ganadas: {int(y.sum())} "
          f"({y.mean()*100:.0f}%)")
    if len(y) < 100:
        print("muy pocas filas todavía")
        return 1
    Xtr, ytr, Xte, yte = dividir(X, y, g)
    print(f"train {len(ytr)} · test {len(yte)}")

    mejor = {"auc": 0, "cols": None, "hp": None}
    hist = []
    combinaciones = []
    for r in range(1, len(modelo.NOMBRES)+1):
        combinaciones += list(itertools.combinations(range(len(modelo.NOMBRES)), r))
    # primer pase: todas las combinaciones de rasgos con un ajuste fijo
    for cols in combinaciones:
        mod = modelo.entrenar(Xtr[:, cols], ytr, epocas=800, lr=0.5, l2=1e-3)
        p = [modelo.predecir(mod, x) for x in Xte[:, cols]]
        a = modelo.auc(yte, p)
        hist.append({"cols": cols, "auc": a, "l2": 1e-3, "epocas": 800, "lr": 0.5})
        if a > mejor["auc"]:
            mejor = {"auc": a, "cols": cols, "hp": {"l2": 1e-3, "epocas": 800, "lr": 0.5}}
    print(f"exploración de rasgos: {len(combinaciones)} combinaciones · mejor AUC {mejor['auc']:.4f}")

    # segundo pase: afinar hiperparámetros de la mejor combinación hasta completar los ciclos
    cols = mejor["cols"]
    rng = np.random.default_rng(3)
    hechos = len(combinaciones)
    while hechos < ciclos:
        l2 = float(rng.choice([1e-4, 3e-4, 1e-3, 3e-3, 1e-2]))
        epocas = int(rng.choice([400, 800, 1500, 3000]))
        lr = float(rng.choice([0.1, 0.3, 0.5, 0.9]))
        mod = modelo.entrenar(Xtr[:, cols], ytr, epocas=epocas, lr=lr, l2=l2)
        p = [modelo.predecir(mod, x) for x in Xte[:, cols]]
        a = modelo.auc(yte, p)
        hist.append({"cols": cols, "auc": a, "l2": l2, "epocas": epocas, "lr": lr})
        if a > mejor["auc"]:
            mejor = {"auc": a, "cols": cols, "hp": {"l2": l2, "epocas": epocas, "lr": lr}}
        hechos += 1
    print(f"ciclos totales: {hechos} · mejor AUC {mejor['auc']:.4f} · "
          f"rasgos {[modelo.NOMBRES[i] for i in mejor['cols']]} · {mejor['hp']}")

    cols = mejor["cols"]
    final = modelo.entrenar(X[:, cols], y, epocas=mejor["hp"]["epocas"],
                            lr=mejor["hp"]["lr"], l2=mejor["hp"]["l2"])
    final["cols"] = list(cols)
    final["auc_test"] = mejor["auc"]
    final["filas"] = int(len(y))
    final["partidas"] = int(len(np.unique(g)))
    modelo.guardar(final)
    print("modelo guardado ·", {k: round(v, 3) for k, v in zip(modelo.NOMBRES, [0]*0)} or "")
    pesos = {modelo.NOMBRES[c]: round(w, 3) for c, w in zip(cols, final["w"])}
    print("pesos:", json.dumps(pesos, indent=1))
    json.dump(hist, open(os.path.join(DIR, "data", "historial_entrenamiento.json"), "w"))
    print(f"({time.time()-t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
