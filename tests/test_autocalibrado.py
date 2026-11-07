"""La calibración automática debe encontrar una rejilla sintética sin ayuda."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw
import random
from coach.autocalibrado import detectar_rejilla
from coach import refinar as refino, deteccion

ICONOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "iconos", "items")
ids = [f for f in os.listdir(ICONOS) if f.endswith("_n.png")]

def fabricar(filas=10, cols=8, lado=54, margen=40, W=2560, H=1440):
    im = Image.new("RGB", (W, H), (11, 14, 19))
    d = ImageDraw.Draw(im)
    x0 = (W - (cols*lado + (cols-1)*6))//2
    y0 = (H - (filas*lado + (filas-1)*6))//2
    for f in range(filas):
        for c in range(cols):
            icono = Image.open(os.path.join(ICONOS, random.choice(ids))).convert("RGB").resize((lado, lado))
            im.paste(icono, (x0 + c*(lado+6), y0 + f*(lado+6)))
    # Ruta privada: con un nombre fijo en /tmp, dos corridas a la vez (o el test
    # corriendo junto a otro proceso) se pisaban la imagen y el acierto se hundía.
    import tempfile
    fd, ruta = tempfile.mkstemp(prefix="marcador_sintetico_", suffix=".png")
    os.close(fd)
    im.save(ruta)
    return ruta, (x0, y0, cols*lado + (cols-1)*6, filas*lado + (filas-1)*6)


def main():
    # La semilla va DENTRO de main: con pytest los módulos se importan antes de
    # ejecutarse y la semilla del import se pisaba entre suites (fallo de hoy).
    random.seed(5)
    fallos = 0
    for filas, cols, lado in ((10, 8, 54), (10, 8, 40), (10, 8, 72)):
        ruta, caja = fabricar(filas, cols, lado)
        r = detectar_rejilla(ruta)
        if not r:
            print(f"  FALLA {filas}x{cols} lado {lado}: no detectó rejilla")
            fallos += 1
            os.unlink(ruta)
            continue
        ok_n = (abs(r["ny"]-filas) <= 1 and abs(r["nx"]-cols) <= 1)
        punt, x0, y0, paso = refino.refinar(ruta, r)
        celdas = refino._celdas(x0, y0, paso, r["nx"], r["ny"], r["ancho_analisis"], r["alto_analisis"])
        leido = deteccion.leer_celdas(ruta, celdas)
        aciertos = sum(1 for f in leido for c in f if c.get("id"))
        total = r["nx"]*r["ny"]
        tasa = aciertos/total
        print(f"  {filas}x{cols} lado {lado}: detectó {r['ny']}x{r['nx']} · paso {paso} · "
              f"iconos reconocidos {tasa*100:.0f}%")
        os.unlink(ruta)
        if not ok_n or tasa < 0.70:
            fallos += 1

    print("autocalibrado:", "OK" if fallos == 0 else f"{fallos} fallos")
    return fallos


def test_suite():
    """Entrada para `pytest -q`: la suite devuelve el número de fallos."""
    assert main() == 0

if __name__ == "__main__":
    sys.exit(main())
