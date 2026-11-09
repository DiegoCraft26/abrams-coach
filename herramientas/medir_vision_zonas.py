#!/usr/bin/env python3
"""Mide la visión por zonas: recortes pequeños en vez del cuadro entero.

El cuadro completo a 640 px no deja leer el reloj ni el texto de la tienda y cuesta
~3 600 tokens por lectura. La apuesta es que un recorte de 6-15 kB de la zona que
interesa se lee mejor y más rápido.

Uso:
    python3 herramientas/medir_vision_zonas.py                 # solo recorta y guarda
    python3 herramientas/medir_vision_zonas.py --enviar        # y pregunta al modelo
    python3 herramientas/medir_vision_zonas.py --enviar --salida /tmp/zonas

Deja los recortes en `salida/vision-zonas/<hora>/` para poder probar de nuevo sin gastar
cuota.
"""
import argparse
import json
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.fuentes import captura_bajo_demanda as cbd  # noqa: E402

# Preguntas por zona. Todas piden JSON mínimo: cada token de más se paga en cada cuadro.
PREGUNTAS = {
    "tiempo": ('Es el reloj de la partida de Deadlock (arriba al centro, formato M:SS). '
               'Devuelve SOLO {"reloj_s": <segundos totales>} o {"reloj_s": null} si no '
               'se lee con claridad.'),
    "almas": ('Es el contador de almas de Deadlock (el número grande al centro-abajo). '
              'Devuelve SOLO {"almas": <número>} o {"almas": null}.'),
    "mis_items": ('Es la fila de tus ítems en el HUD de Deadlock. Devuelve SOLO '
                  '{"items": <cuántos huecos tienen ítem>, "huecos": <total visible>}.'),
    "centro": ('¿Está abierta la tienda de Deadlock (panel grande con ítems y precios)? '
               'Devuelve SOLO {"tienda_abierta": true|false}.'),
}


def caja_frac(region, juego):
    """Convierte [x, y, ancho, alto] en fracciones del área de juego a píxeles."""
    jx, jy, jw, jh = juego
    x, y, ancho, alto = region
    return (jx + int(x * jw), jy + int(y * jh), int(ancho * jw), int(alto * jh))


def recortar(cuadro, caja):
    x, y, ancho, alto = caja
    return cuadro.crop((x, y, x + ancho, y + alto))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enviar", action="store_true", help="preguntar al modelo")
    ap.add_argument("--salida", default=os.path.join(RAIZ, "salida", "vision-zonas"))
    ap.add_argument("--zona", action="append", default=None,
                    help="limitar a una zona (se puede repetir)")
    a = ap.parse_args()

    from coach.agente import vision as V

    juego = cbd.caja_juego()
    if juego is None:
        print("no pude localizar el monitor del juego (kscreen-doctor)")
        return 2
    cuadro = cbd._capturar()
    if cuadro is None:
        print("no pude capturar la pantalla")
        return 2
    print(f"escritorio {cuadro.size} · juego en {juego}")

    with open(os.path.join(RAIZ, "config", "regiones.json"), encoding="utf-8") as f:
        regiones = json.load(f)

    # Las zonas de config/regiones.json van en fracciones del ÁREA DE JUEGO, que aquí es
    # justo el monitor del juego (el juego va a pantalla completa).
    zonas = {k: v for k, v in regiones.items()
             if isinstance(v, list) and len(v) == 4}
    zonas["centro"] = [0.22, 0.18, 0.56, 0.64]
    if a.zona:
        zonas = {k: v for k, v in zonas.items() if k in a.zona}

    carpeta = os.path.join(a.salida, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(carpeta, exist_ok=True)

    proveedor = None
    if a.enviar:
        from coach.agente import proveedor as P
        proveedor = P.RespaldoVision()

    resultados = {}
    for nombre, region in zonas.items():
        caja = caja_frac(region, juego)
        recorte = recortar(cuadro, caja)
        jpeg = V.cuadro_a_jpeg(recorte)
        ruta = os.path.join(carpeta, f"{nombre}.jpg")
        with open(ruta, "wb") as f:
            f.write(jpeg)
        fila = {"caja": caja, "peso_kb": round(len(jpeg) / 1024, 1), "archivo": ruta}
        if proveedor is not None:
            inicio = time.perf_counter()
            try:
                respuesta = proveedor.chat_vision(
                    jpeg, PREGUNTAS.get(nombre, "Describe el JSON pedido."),
                    sistema="Responde SOLO el JSON pedido, sin explicaciones ni markdown.",
                    timeout_s=25)
                texto = V.contenido(respuesta)
                fila["latencia_s"] = round(time.perf_counter() - inicio, 2)
                fila["tokens"] = (respuesta.get("usage") or {}).get("total_tokens")
                try:
                    fila["json"] = V._extraer_json(texto)
                except ValueError:
                    fila["json"] = None
                    fila["crudo"] = texto[:120]
            except Exception as exc:                      # noqa: BLE001
                fila["error"] = f"{type(exc).__name__}: {exc}"[:120]
                fila["latencia_s"] = round(time.perf_counter() - inicio, 2)
        resultados[nombre] = fila
        print(f"  {nombre:10s} {fila['peso_kb']:6.1f} kB  "
              f"{fila.get('latencia_s', '-'):>6} s  {fila.get('tokens', '-'):>5} tok  "
              f"{json.dumps(fila.get('json'), ensure_ascii=False) if 'json' in fila else fila.get('error', '')}")

    # Contra la verdad del OCR local, que es barato y ya está probado.
    from coach.fuentes import hud_rapido
    hud = hud_rapido.leer_actual()
    print(f"\nOCR local del HUD: {hud}")
    print(f"recortes en {carpeta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
