"""EnemyGrid: los 5 enemigos con almas y KDA. La amenaza se lee de un vistazo."""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import elipse, etiqueta, fila, fmt_num, nombre_heroe, vaciar


def _clave(heroe):
    return str(heroe or "").lower().replace(" ", "_").replace("-", "_")


class EnemyGrid(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._filas = {}
        self.lbl_vacio = etiqueta("sin enemigos todavía", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        enemigos = (d or {}).get("enemigos") or []
        firma = tuple((e.get("heroe"), e.get("almas"), e.get("bajas"),
                       e.get("muertes"), e.get("asistencias")) for e in enemigos)
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not enemigos:
            self.append(self.lbl_vacio)
            return
        maximo = max((e.get("almas") or 0) for e in enemigos) or 1
        for e in enemigos:
            self.append(self._fila_enemigo(e, maximo))

    def _fila_enemigo(self, e, maximo):
        nombre = nombre_heroe(e.get("heroe"))
        caja = fila(8)
        caja.add_css_class("fila-enemigo")

        pb = pixbuf(_clave(e.get("heroe")), "heroes", 26)
        icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("avatar-default")
        if not pb:
            icono.set_pixel_size(18)
        icono.set_valign(Gtk.Align.CENTER)
        caja.append(icono)

        nom = etiqueta(nombre, "t13 fuerte")
        nom.set_size_request(74, -1)
        # Con solo elipsis el nombre largo crecía y desalineaba la columna de almas:
        # max_width_chars fija el techo y el tooltip deja leer el nombre entero.
        elipse(nom, 10)
        caja.append(nom)

        almas = etiqueta(fmt_num(e.get("almas")), "almas num")
        almas.set_size_request(56, -1)
        almas.set_xalign(1)
        caja.append(almas)

        kda = e.get("bajas")
        txt = (f"{kda}/{e.get('muertes', 0)}/{e.get('asistencias', 0)}"
               if kda is not None else "")
        caja.append(etiqueta(txt, "kda"))

        # Barra relativa al que más almas tiene: mide la amenaza, no el valor absoluto.
        # Se dibuja con cajas y no con Gtk.LevelBar porque su "slider" interno reporta
        # tamaños mínimos negativos y GTK llena el log de avisos en cada repintado.
        caja.append(self._barra(e.get("almas") or 0, maximo))
        return caja

    def _barra(self, valor, maximo, ancho=64, alto=6):
        fondo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        fondo.set_size_request(ancho, alto)
        fondo.set_valign(Gtk.Align.CENTER)
        fondo.add_css_class("barra-fondo")
        relleno = Gtk.Box()
        fraccion = 0.0 if not maximo else max(0.0, min(1.0, valor / maximo))
        relleno.set_size_request(max(1, int(ancho * fraccion)), alto)
        relleno.add_css_class("barra-valor")
        fondo.append(relleno)
        return fondo
