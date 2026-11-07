"""Verifica el reconocimiento de iconos con imágenes sintéticas (sin el juego)."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image
import numpy as np
from coach import deteccion

random.seed(7)
ids, M = deteccion.matrices("items")
print(f"plantillas: {len(ids)}")

def prueba(relleno=1.0, ruido=8, n=40, fondo=(14,18,24)):
    aciertos = 0
    for _ in range(n):
        pid = random.choice(ids)
        ref = Image.open(os.path.join(deteccion.ICONOS, "items", f"{pid}_n.png")).convert("RGB")
        lado = int(64*relleno)
        icono = ref.resize((lado, lado))
        lienzo = Image.new("RGB", (64, 64), fondo)
        ox = (64-lado)//2; oy = (64-lado)//2
        lienzo.paste(icono, (ox, oy))
        if ruido:
            a = np.asarray(lienzo, dtype=np.int16)
            a = np.clip(a + np.random.randint(-ruido, ruido+1, a.shape), 0, 255).astype(np.uint8)
            lienzo = Image.fromarray(a)
        mejor, punt = deteccion.identificar(lienzo, "items", top=1)[0]
        if mejor == pid:
            aciertos += 1
    return aciertos/n

print("Reconocimiento con imágenes sintéticas:")
for relleno, ruido, et in [(1.0,0,"icono llena la celda, sin ruido"),
                           (1.0,10,"icono llena la celda, ruido leve"),
                           (0.85,10,"85% de la celda, ruido leve"),
                           (0.70,15,"70% de la celda, ruido fuerte")]:
    print(f"  {et:36} {prueba(relleno, ruido)*100:5.1f}%")


def test_suite():
    """Entrada para `pytest -q`: con el icono limpio el reconocimiento es casi exacto.

    La semilla se fija aquí (no en el import): con pytest los módulos se importan antes
    de ejecutarse y la semilla del import se la comían otras suites. Medido: 90%.
    """
    random.seed(7)
    assert prueba(1.0, 0) >= 0.90
