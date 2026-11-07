"""Ayudas comunes de los componentes: etiquetas, tarjetas y vaciado de contenedores."""
from gi.repository import Gtk, Pango


def etiqueta(texto="", clase="t13", xalign=0.0):
    l = Gtk.Label(label=texto)
    if clase:
        for c in clase.split():
            l.add_css_class(c)
    l.set_xalign(xalign)
    return l


def elipse(l, ancho_chars=24):
    l.set_ellipsize(Pango.EllipsizeMode.END)
    l.set_max_width_chars(ancho_chars)
    l.set_tooltip_text(l.get_text() or None)
    return l


def envolver(l, chars=42):
    l.set_wrap(True)
    l.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    l.set_max_width_chars(chars)
    return l


def tarjeta(vertical=True, spacing=8, clase="tarjeta"):
    caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)
    for c in clase.split():
        caja.add_css_class(c)
    return caja


def fila(spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def vaciar(contenedor):
    """Quita todos los hijos de un Gtk.Box/FlowBox."""
    hijo = contenedor.get_first_child()
    while hijo:
        sig = hijo.get_next_sibling()
        contenedor.remove(hijo)
        hijo = sig


def imagen(ident, tipo="items", lado=48):
    from ..iconos import pixbuf
    pb = pixbuf(ident, tipo, lado)
    img = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
    if not pb:
        img.set_pixel_size(int(lado * 0.6))
    return img


def clase_unica(widget, clases, nueva):
    """Deja una sola clase de un grupo (chips de estado, insignias)."""
    for c in clases:
        widget.remove_css_class(c)
    if nueva:
        widget.add_css_class(nueva)


def fmt_num(valor):
    """Número con separador de miles; None -> raya."""
    if valor is None:
        return "—"
    try:
        return f"{int(valor):,}"
    except (TypeError, ValueError):
        return "—"


def reloj(segundos):
    if segundos is None:
        return "--:--"
    s = int(segundos)
    return f"{s//60}:{s%60:02d}"


def desacoplar(widget):
    """Saca el widget de su padre actual.

    Los componentes se mueven entre columnas al cambiar de breakpoint: si un widget ya
    tiene padre, `append()` provoca un aviso de GTK y el widget se queda duplicado.
    """
    while widget.get_parent() is not None:
        widget.unparent()
    return widget
