#!/usr/bin/env python3
"""Diagnóstico de primera vez: captura varias veces y reporta qué puede leer.

Sirve para saber, sin jugar una partida completa, si la app ve la pantalla.
"""
import json, os, sys, time
sys.path.insert(0, RAIZ)
from coach import lector, deteccion, autocalibrado

# Este script vive en herramientas/calibracion/: la raíz del repo está 2
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SALIDA = os.path.join(RAIZ, "salida", "diagnostico")


def main(n=6, espera=3.0, etiqueta="diag"):
    os.makedirs(SALIDA, exist_ok=True)
    cfg = lector.cargar_cfg()
    informe = []
    print(f"capturando {n} veces cada {espera:.0f}s… (abre el juego y el marcador)")
    for i in range(n):
        try:
            img = lector.capturar(os.path.join(SALIDA, f"{etiqueta}-{i:02d}.png"))
        except Exception as e:
            print(f"  [{i}] no pude capturar: {e}")
            time.sleep(espera)
            continue
        fila = {"i": i, "hora": time.strftime("%H:%M:%S")}
        t, ok_t = lector.leer_tiempo(img, cfg)
        a, ok_a = lector.leer_almas(img, cfg)
        fila.update(tiempo=t, tiempo_ok=ok_t, almas=a, almas_ok=ok_a)

        auto = autocalibrado.detectar_rejilla(img)
        if auto:
            fila["rejilla"] = f"{auto['ny']}x{auto['nx']}"
            fila["fuerza"] = auto["fuerza"]
            celdas = auto.get("candidatas", [None])[0]
            if celdas:
                leido = deteccion.leer_celdas(img, celdas, umbral=0.55)
                fila["iconos_leidos"] = sum(1 for f in leido for c in f if c.get("id"))
                fila["iconos_total"] = sum(len(f) for f in leido)
        else:
            fila["rejilla"] = None

        heroes = lector.leer_heroes(img, cfg)
        fila["heroes"] = [h for h in heroes if h][:10]

        informe.append(fila)
        print(f"  [{i}] {fila['hora']} · tiempo {t} (ok={ok_t}) · almas {a} (ok={ok_a}) · "
              f"rejilla {fila.get('rejilla')} · iconos {fila.get('iconos_leidos','-')}"
              f"/{fila.get('iconos_total','-')} · héroes {len(fila['heroes'])}")
        time.sleep(espera)

    ruta = os.path.join(SALIDA, f"informe-{etiqueta}.json")
    json.dump(informe, open(ruta, "w"), ensure_ascii=False, indent=1)
    con_tiempo = sum(1 for f in informe if f.get("tiempo_ok"))
    con_almas = sum(1 for f in informe if f.get("almas_ok"))
    con_rejilla = sum(1 for f in informe if f.get("rejilla"))
    con_heroes = sum(1 for f in informe if f.get("heroes"))
    print(f"\nresumen: tiempo {con_tiempo}/{len(informe)} · almas {con_almas}/{len(informe)} · "
          f"rejilla {con_rejilla}/{len(informe)} · héroes {con_heroes}/{len(informe)}")
    print(f"informe: {ruta}")
    return 0 if (con_tiempo and con_almas) else 1


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    sys.exit(main(n))
