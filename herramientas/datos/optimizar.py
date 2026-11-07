#!/usr/bin/env python3
"""Bucle de mejora: busca pesos que maximicen el acierto contra partidas reales."""
import itertools, json, random, sys, time
sys.path.insert(0, ".")
from coach import evaluador
from coach.motor_api import Motor

# Este script vive en herramientas/datos/: la raíz del repo está 3
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ESPACIO = {
    "w_lift":    [0.3, 0.6, 1.0, 1.4],
    "w_counter": [0.2, 0.5, 0.75, 1.1],
    "w_cadena":  [0.4, 0.9, 1.4, 2.0],
    "w_tiempo":  [0.08, 0.15, 0.22, 0.32],
    "w_flujo":   [0.0, 0.5, 1.0],
    "lift_minimo": [-0.03, -0.015, 0.0],
}


def main():
    n_partidas = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    iteraciones = int(sys.argv[2]) if len(sys.argv) > 2 else 160
    partidas = evaluador.descargar(n_partidas)
    m = Motor()
    casos, cob = evaluador.construir_casos(partidas, m.conoc, m.cat)
    print(f"partidas {len(partidas)} · casos {cob[0]}/{cob[1]} ({cob[0]/cob[1]*100:.0f}%)")

    base = evaluador.evaluar(casos, m)
    print(f"base: top1 {base[0]*100:.1f}% · top3 {base[1]*100:.1f}%")

    random.seed(11)
    claves = list(ESPACIO)
    mejor = (base[1], base[0], {})
    vistos = set()
    t0 = time.time()
    for it in range(iteraciones):
        cfg = {k: random.choice(ESPACIO[k]) for k in claves}
        firma = tuple(sorted(cfg.items()))
        if firma in vistos:
            continue
        vistos.add(firma)
        a1, a3, _ = evaluador.evaluar(casos, m, cfg)
        if (a3, a1) > (mejor[0], mejor[1]):
            mejor = (a3, a1, cfg)
            print(f"  [{it}] top3 {a3*100:.1f}% · top1 {a1*100:.1f}%  {cfg}")
    print(f"\nmejor: top3 {mejor[0]*100:.1f}% · top1 {mejor[1]*100:.1f}%")
    print("config:", json.dumps(mejor[2], indent=1))
    print(f"({time.time()-t0:.0f} s)")
    json.dump(mejor[2], open("data/mejor_config.json", "w"), indent=1)


if __name__ == "__main__":
    main()
