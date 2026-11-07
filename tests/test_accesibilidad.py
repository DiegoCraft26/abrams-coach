"""Contraste de la interfaz (WCAG AA) calculado sobre `coach/ui/tema.css`.

No hace falta abrir la ventana: se leen los colores del tema y se calculan los contrastes
de los pares que de verdad se usan. Si alguien oscurece el texto secundario o cambia el
acento por uno más apagado, esto falla antes de que nadie lo note mirando la pantalla.
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMA = os.path.join(RAIZ, "coach", "ui", "tema.css")

# Pares (clase del texto, clase del fondo). Los colores se leen del CSS, no se copian
# aquí: si alguien cambia el tema, la prueba mide el tema nuevo. El mínimo es 4.5:1 para
# texto normal y 3:1 para texto grande (>= 18 px o 14 px en negrita).
PARES = [
    ("Texto principal sobre fondo", ".fuerte", "window.coach", 4.5),
    ("Texto principal sobre tarjeta", ".fuerte", ".tarjeta", 4.5),
    ("Texto secundario sobre fondo", ".tenue", "window.coach", 4.5),
    ("Texto secundario sobre tarjeta", ".tenue", ".tarjeta", 4.5),
    ("Acento sobre tarjeta", ".acento", ".tarjeta", 4.5),
    ("Aviso sobre tarjeta", ".aviso", ".tarjeta", 4.5),
    ("Error sobre tarjeta", ".error", ".tarjeta", 4.5),
    ("Info sobre tarjeta", ".info", ".tarjeta", 3.0),
    ("Pie sobre fondo", ".pie", "window.coach", 4.5),
    ("Pill sobre tarjeta", ".pill", ".tarjeta", 4.5),
]


def _rgb(hexadecimal):
    h = hexadecimal.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _luminancia(color):
    def canal(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(uno, otro):
    """Relación de contraste WCAG entre dos colores hex."""
    l1, l2 = _luminancia(_rgb(uno)), _luminancia(_rgb(otro))
    claro, oscuro = max(l1, l2), min(l1, l2)
    return (claro + 0.05) / (oscuro + 0.05)


def _bloques(css):
    """selector -> {propiedad: valor} de un CSS sencillo (sin anidar)."""
    # Los comentarios del CSS se cuelan en el selector y rompen el mapa.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    salida = {}
    for bloque in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selectores, cuerpo = bloque
        props = {}
        for linea in cuerpo.split(";"):
            if ":" in linea:
                k, v = linea.split(":", 1)
                props[k.strip()] = v.strip()
        for sel in selectores.split(","):
            sel = sel.strip()
            if sel and not sel.startswith("@"):
                salida.setdefault(sel, {}).update(props)
    return salida


def color_de(bloque, propiedad="color"):
    """Primer valor hex de esa propiedad, o None."""
    valor = bloque.get(propiedad)
    if not valor:
        return None
    m = re.search(r"#[0-9a-fA-F]{6}", valor)
    return m.group(0) if m else None


def _colores_del_tema():
    """Todos los hex que aparecen en el CSS, para saber si algún par no existe ya."""
    try:
        with open(TEMA, encoding="utf-8") as f:
            css = f.read()
    except OSError:
        return set()
    return {c.upper() for c in re.findall(r"#[0-9a-fA-F]{6}\b", css)}


def main():
    fallos = 0
    if not os.path.exists(TEMA):
        print(f"no existe {TEMA}")
        return 1
    presentes = _colores_del_tema()

    print("contraste de los pares usados (colores leídos del CSS)")
    with open(TEMA, encoding="utf-8") as f:
        bloques = _bloques(f.read())
    for nombre, sel_texto, sel_fondo, minimo in PARES:
        texto = color_de(bloques.get(sel_texto, {}))
        fondo = color_de(bloques.get(sel_fondo, {}), "background-color")
        if not texto or not fondo:
            print(f"  FALLA {nombre}: no encuentro los colores en el CSS "
                  f"({sel_texto} / {sel_fondo})")
            fallos += 1
            continue
        razon = contraste(texto, fondo)
        etiqueta = "ok  " if razon >= minimo else "FALLA"
        print(f"  {etiqueta} {nombre:32} {razon:4.1f}:1 (mínimo {minimo})")
        if razon < minimo:
            fallos += 1

    print("ratios imposibles")
    # el mismo color consigo mismo debe dar 1.0; si no, las cuentas están mal
    if abs(contraste("#FFFFFF", "#FFFFFF") - 1.0) > 1e-6:
        print("  FALLA el cálculo de contraste está roto")
        fallos += 1
    else:
        print("  ok   blanco con blanco da 1.0")
    if not (contraste("#FFFFFF", "#000000") > 20):
        print("  FALLA blanco con negro debería pasar de 20:1")
        fallos += 1
    else:
        print(f"  ok   blanco con negro da {contraste('#FFFFFF', '#000000'):.1f}:1")

    print()
    if fallos:
        print(f"accesibilidad: {fallos} fallos")
        return 1
    print("accesibilidad: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
