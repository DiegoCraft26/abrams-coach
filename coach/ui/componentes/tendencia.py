"""TrendChart: tus almas contra la media enemiga a lo largo de la partida.

Se dibuja con `Gtk.DrawingArea` (nada de dependencias): dos polilíneas, rejilla suave y el
último valor. Es lo que ocupa el espacio vertical de la columna principal sin ser ruido.
"""
import math

from gi.repository import Gtk

from .base import etiqueta, fmt_num


class TrendChart(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_size_request(-1, 120)
        self.lbl_vacio = etiqueta("sin historial todavía", "vacio")

        cab = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.lbl_mio = etiqueta("", "t12 num acento")
        self.lbl_suyo = etiqueta("", "t12 num tenue")
        self.lbl_rango = etiqueta("", "t11 tenue num")
        self.lbl_rango.set_hexpand(True)
        self.lbl_rango.set_xalign(1)
        cab.append(self.lbl_mio)
        cab.append(self.lbl_suyo)
        cab.append(self.lbl_rango)
        self.append(cab)

        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._dibujar)
        self.area.set_vexpand(True)
        self.area.set_size_request(-1, 110)
        self.append(self.area)

        self._puntos = []
        self._firma = None
        self.append(self.lbl_vacio)

    def actualizar(self, d):
        hist = (d or {}).get("historial") or []
        firma = (len(hist), hist[-1].get("t") if hist else None,
                 hist[-1].get("a") if hist else None)
        if firma == self._firma:
            return
        self._firma = firma
        # Ordenado por tiempo: el historial llega como deque y, cuando el reloj de la
        # partida vuelve a empezar, los puntos viejos quedan detrás de los nuevos. Sin
        # ordenar, la polilínea retrocede y el rango se leía al revés (30:00 → 20:00).
        self._puntos = sorted(((h.get("t") or 0, h.get("a"), h.get("e"))
                               for h in hist if h.get("a") is not None),
                              key=lambda p: p[0])
        hay = len(self._puntos) >= 2
        self.area.set_visible(hay)
        self.lbl_vacio.set_visible(not hay)
        if not hay:
            for l in (self.lbl_mio, self.lbl_suyo, self.lbl_rango):
                l.set_label("")
            return
        ult = self._puntos[-1]
        prim = self._puntos[0]
        self.lbl_mio.set_label(f"tú {fmt_num(ult[1])}")
        self.lbl_suyo.set_label(f"media enemiga {fmt_num(ult[2])}" if ult[2] is not None
                                else "")
        self.lbl_rango.set_label(f"{int(prim[0])//60}:{int(prim[0])%60:02d} → "
                                 f"{int(ult[0])//60}:{int(ult[0])%60:02d} "
                                 f"· {len(self._puntos)} muestras")
        self.area.queue_draw()

    def _dibujar(self, area, cr, ancho, alto):
        puntos = self._puntos[-160:]
        if len(puntos) < 2:
            return
        margen = 6
        xs = [p[0] for p in puntos]
        ys = [v for p in puntos for v in (p[1], p[2]) if v is not None]
        if not ys:
            return
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x1 == x0:
            x1 = x0 + 1
        if y1 == y0:
            y1 = y0 + 1
        alto_util = max(1, alto - 2 * margen)
        ancho_util = max(1, ancho - 2 * margen)

        def px(t):
            return margen + (t - x0) / (x1 - x0) * ancho_util

        def py(v):
            return alto - margen - (v - y0) / (y1 - y0) * alto_util

        # rejilla
        cr.set_line_width(1)
        cr.set_source_rgba(1, 1, 1, 0.05)
        for i in range(1, 4):
            y = margen + alto_util * i / 4
            cr.move_to(margen, y)
            cr.line_to(ancho - margen, y)
        cr.stroke()

        # media enemiga (tenue) y mis almas (acento)
        for indice, (color, r, g, b) in enumerate(((0.35, 0.45, 0.65, 0.75),
                                                   (0.24, 0.86, 0.52, 1.0))):
            cr.set_source_rgba(r, g, b, color)
            cr.set_line_width(2.0 if indice else 1.4)
            primero = True
            for t, a, e in puntos:
                valor = e if indice == 0 else a
                if valor is None:
                    continue
                if primero:
                    cr.move_to(px(t), py(valor))
                    primero = False
                else:
                    cr.line_to(px(t), py(valor))
            cr.stroke()

        # eje de tiempo: marcas cada cuarto
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.set_line_width(1)
        for i in range(1, 4):
            x = margen + ancho_util * i / 4
            cr.move_to(x, margen)
            cr.line_to(x, alto - margen)
        cr.stroke()

        # último valor de mis almas
        ultimo = next((p for p in reversed(puntos) if p[1] is not None), None)
        if ultimo:
            cr.arc(px(ultimo[0]), py(ultimo[1]), 3.0, 0, 2 * math.pi)
            cr.set_source_rgba(0.43, 0.90, 0.52, 1.0)
            cr.fill()
