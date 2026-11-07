#!/usr/bin/env python3
"""Panel nativo GTK4: la misma información que el panel web sin abrir un navegador.

Costo real medido: el servidor del coach son ~24 MB; una pestaña de Brave ~300-400 MB.
Este panel dibuja lo mismo con GTK4 y carga los iconos desde disco.

Uso:  python3 panel_nativo.py [--pantalla 2] [--url http://127.0.0.1:8090]
"""
import argparse, json, os, sys, threading, time, urllib.request

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
ICONOS = os.path.join(DIR, "data", "iconos")

CSS = """
window { background-color: #080a0e; }
.vivo { color: #3ddc84; font-size: 12px; font-weight: 700; }
.muerto { color: #ff5c5c; font-size: 12px; font-weight: 700; }
.hora { color: #f2f6fc; font-size: 17px; font-weight: 700; }
.meta { color: #a8b6c8; font-size: 14px; }
.chip { font-size: 13px; font-weight: 800; padding: 8px 18px; border-radius: 999px; }
.chip-farm { color: #ffb544; background: rgba(255,181,68,.14); }
.chip-pelear { color: #3ddc84; background: rgba(61,220,132,.14); }
.chip-equilibrio, .chip-inicio { color: #5aa9f0; background: rgba(90,169,240,.14); }
.tarjeta { background: linear-gradient(160deg, #171e28, #0d1117); border-radius: 18px; padding: 18px; }
.et { color: #7b8a9e; font-size: 11px; font-weight: 800; }
.titulo { color: #f2f6fc; font-size: 32px; font-weight: 800; }
.precio { color: #a8b6c8; font-size: 17px; }
.razon { color: #a8b6c8; font-size: 15px; }
.contexto { color: #7b8a9e; font-size: 13px; }
.rotulo { color: #7b8a9e; font-size: 10px; font-weight: 800; }
.pill { background: #12171f; border-radius: 999px; padding: 5px 12px; color: #a8b6c8; font-size: 12px; }
.pie { color: #7b8a9e; font-size: 11px; }
.slot { background: #0d1117; border-radius: 10px; }
.slot-bien { border: 1px solid rgba(61,220,132,.55); }
.slot-mal { border: 1px solid rgba(255,92,92,.55); }
.slot-vacio { border: 1px dashed #1e2734; }
.val { color: #3ddc84; font-size: 10px; font-weight: 700; }
.val-mal { color: #ff5c5c; font-size: 10px; font-weight: 700; }
"""


def cargar_icono(iid, tipo="items", lado=48):
    """Carga el icono desde disco sin pasar por la red."""
    for ext in (".webp", ".png"):
        ruta = os.path.join(ICONOS, tipo, f"{iid}{ext}")
        if os.path.exists(ruta):
            try:
                from gi.repository import GdkPixbuf
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(ruta, lado, lado, True)
            except Exception:
                return None
    return None


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app, url):
        super().__init__(application=app, title="Abrams Coach")
        self.url = url
        self.set_default_size(960, 1080)
        self.set_size_request(640, 480)
        self.add_css_class("fondo")
        self._construir()
        self._ultimo = 0.0
        GLib.timeout_add_seconds(1, self._refrescar)

    # ---------- construcción ----------
    def _et(self, texto, clase):
        l = Gtk.Label(label=texto)
        l.add_css_class(clase)
        l.set_xalign(0)
        return l

    def _construir(self):
        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        raiz.set_margin_top(22); raiz.set_margin_bottom(22)
        raiz.set_margin_start(22); raiz.set_margin_end(22)
        self.set_child(raiz)

        # cabecera
        cab = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.lbl_vivo = self._et("● conectando", "vivo")
        cab.append(self.lbl_vivo)
        self.lbl_hora = self._et("--:--", "hora")
        cab.append(self.lbl_hora)
        self.lbl_meta = self._et("", "meta")
        self.lbl_meta.set_hexpand(True)
        cab.append(self.lbl_meta)
        self.lbl_chip = self._et("—", "chip chip-inicio")
        self.lbl_chip.set_xalign(1)
        cab.append(self.lbl_chip)
        raiz.append(cab)

        # tarjeta principal
        tarjeta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=26)
        tarjeta.add_css_class("tarjeta")
        tarjeta.set_vexpand(False)
        self.img_item = Gtk.Picture()
        self.img_item.set_size_request(210, 210)
        tarjeta.append(self.img_item)
        detalle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detalle.set_valign(Gtk.Align.CENTER)
        self.lbl_et = self._et("COMPRA AHORA", "et")
        detalle.append(self.lbl_et)
        self.lbl_titulo = self._et("Esperando partida", "titulo")
        self.lbl_titulo.set_wrap(True)
        detalle.append(self.lbl_titulo)
        self.lbl_precio = self._et("", "precio")
        detalle.append(self.lbl_precio)
        self.lbl_razon = self._et("", "razon")
        self.lbl_razon.set_wrap(True)
        self.lbl_razon.set_max_width_chars(46)
        detalle.append(self.lbl_razon)
        self.lbl_contexto = self._et("", "contexto")
        self.lbl_contexto.set_wrap(True)
        self.lbl_contexto.set_max_width_chars(46)
        detalle.append(self.lbl_contexto)
        tarjeta.append(detalle)
        raiz.append(tarjeta)

        # tiras
        self.fila_vs = self._tira("VS")
        self.fila_vs["caja"].remove(self.fila_vs["contenido"])
        flujo = Gtk.FlowBox()
        flujo.set_selection_mode(Gtk.SelectionMode.NONE)
        flujo.set_max_children_per_line(2)
        flujo.set_min_children_per_line(1)
        flujo.set_column_spacing(8)
        flujo.set_row_spacing(6)
        self.fila_vs["caja"].append(flujo)
        self.fila_vs["contenido"] = flujo
        raiz.append(self.fila_vs["caja"])
        self.fila_compras = self._tira("COMPRAS")
        raiz.append(self.fila_compras["caja"])
        self.fila_sigue = self._tira("SIGUE")
        raiz.append(self.fila_sigue["caja"])
        self.fila_ahorro = self._tira("AHORRANDO")
        raiz.append(self.fila_ahorro["caja"])

        # inventario
        self.inv = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.inv.set_homogeneous(True)
        raiz.append(self.inv)

        # pie
        self.lbl_pie = self._et("", "pie")
        self.lbl_pie.set_xalign(0.5)
        raiz.append(self.lbl_pie)

    def _tira(self, rotulo):
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = self._et(rotulo, "rotulo")
        lbl.set_size_request(70, -1)
        caja.append(lbl)
        contenido = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        caja.append(contenido)
        return {"caja": caja, "contenido": contenido}

    def _pill(self, texto, icono=None, tipo="items"):
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        caja.add_css_class("pill")
        if icono:
            img = Gtk.Picture()
            img.set_size_request(24, 24)
            pb = cargar_icono(icono, tipo, 24)
            if pb:
                img.set_pixbuf(pb)
            caja.append(img)
        caja.append(Gtk.Label(label=texto))
        return caja

    # ---------- datos ----------
    def _pedir(self):
        try:
            with urllib.request.urlopen(self.url + "/api/estado", timeout=2) as r:
                return json.load(r)
        except Exception:
            return None

    def _refrescar(self):
        datos = self._pedir()
        if datos is None:
            self.lbl_vivo.set_label("● sin conexión")
            self.lbl_vivo.remove_css_class("vivo"); self.lbl_vivo.add_css_class("muerto")
            return True
        try:
            self._pintar(datos)
        except Exception as e:
            self.lbl_pie.set_label(f"error: {e}")
        return True

    def _vaciar_tiras(self):
        for clave in ("fila_vs", "fila_sigue", "fila_ahorro"):
            tira = getattr(self, clave)
            hijo = tira["contenido"].get_first_child()
            while hijo:
                sig = hijo.get_next_sibling()
                tira["contenido"].remove(hijo)
                hijo = sig

    def _vaciar_inventario(self):
        hijo = self.inv.get_first_child()
        while hijo:
            sig = hijo.get_next_sibling()
            self.inv.remove(hijo)
            hijo = sig
        for _ in range(12):
            vacio = Gtk.Box()
            vacio.add_css_class("slot"); vacio.add_css_class("slot-vacio")
            vacio.set_size_request(52, 52)
            self.inv.append(vacio)

    def _limpiar(self, mensaje=""):
        """Deja el panel en blanco.

        Sin esto, al terminar la partida quedaban a la vista la hora, las almas y el
        inventario de la partida anterior, con el indicador todavía en verde: se podía
        leer una compra de una partida que ya había acabado. Detectado por QA de UI.
        """
        self.lbl_vivo.set_label("● sin partida")
        self.lbl_vivo.remove_css_class("vivo")
        self.lbl_vivo.add_css_class("muerto")
        self.lbl_hora.set_label("--:--")
        self.lbl_meta.set_label("— almas")
        self.lbl_et.set_label("SIN PARTIDA")
        self.lbl_titulo.set_label("Esperando partida")
        self.lbl_precio.set_label("")
        self.lbl_razon.set_label(mensaje)
        self.lbl_contexto.set_label("")
        self.lbl_chip.set_label("—")
        for c in ("chip-farm", "chip-pelear", "chip-equilibrio", "chip-inicio"):
            self.lbl_chip.remove_css_class(c)
        self.img_item.set_pixbuf(None)
        self._vaciar_tiras()
        self._vaciar_inventario()
        self.lbl_pie.set_label("")

    def _pintar(self, d):
        if not d or d.get("listo") is False:
            self._limpiar((d or {}).get("mensaje", ""))
            return
        fuente = str(d.get("fuente") or "")
        if d.get("rancio"):
            edad = d.get("edad_s")
            self.lbl_vivo.set_label("● datos congelados"
                                    + (f" · hace {round(edad)} s" if edad is not None else ""))
            self.lbl_vivo.remove_css_class("vivo"); self.lbl_vivo.add_css_class("muerto")
        else:
            self.lbl_vivo.set_label("● demo" if fuente == "simulado" else "● en vivo")
            self.lbl_vivo.remove_css_class("muerto"); self.lbl_vivo.add_css_class("vivo")
        t = int(d.get("t") or 0)
        self.lbl_hora.set_label(f"{t//60}:{t%60:02d}")
        almas = d.get("almas")
        econ = d.get("economia") or {}
        dp = econ.get("delta_pct")
        oro = d.get("oro")
        if oro is not None:
            meta = f"{oro:,} sin gastar"
            if almas is not None:
                meta += f"   ·   {almas:,} patrimonio"
        else:
            meta = f"{almas:,} almas" if almas is not None else "— almas"
        if dp is not None:
            meta += f"   ·   {dp*100:+.0f}% vs enemigos"
        self.lbl_meta.set_label(meta)

        est = (d.get("estado") or {}).get("estado") or "INICIO"
        self.lbl_chip.set_label(est)
        for c in ("chip-farm", "chip-pelear", "chip-equilibrio", "chip-inicio"):
            self.lbl_chip.remove_css_class(c)
        self.lbl_chip.add_css_class("chip-" + est.lower())

        recos = d.get("recomendaciones") or []
        if recos:
            r = recos[0]
            pb = cargar_icono(r["id"], "items", 260)
            if pb:
                self.img_item.set_pixbuf(pb)
            self.lbl_et.set_label("COMPRA CON CAMBIO" if r.get("requiere_venta") else "COMPRA AHORA")
            self.lbl_titulo.set_label(r["nombre"])
            if r.get("alcanza") is False:
                self.lbl_et.set_label("AHORRA PARA")
                self.lbl_precio.set_label(f"{r['costo']:,} almas · faltan {r.get('faltan', 0):,}")
            else:
                self.lbl_precio.set_label(f"{r['costo']:,} almas")
            self.lbl_razon.set_label(" · ".join((r.get("razones") or [])[:2]) or "sin datos")
        else:
            self.img_item.set_pixbuf(None)
            self.lbl_et.set_label("SIN COMPRA")
            if d.get("lectura_dudosa"):
                self.lbl_titulo.set_label("No puedo leer bien")
            else:
                self.lbl_titulo.set_label("Fase inicial" if est == "INICIO" else "Sin compra todavía")
            self.lbl_precio.set_label("")
            self.lbl_razon.set_label(" · ".join(d.get("notas") or []) or "ningún ítem pasa el filtro")
        st = d.get("estado") or {}
        self.lbl_contexto.set_label(" · ".join(x for x in (st.get("motivo"), st.get("objetivo")) if x))

        for clave, campo in (("fila_vs", "enemigos"), ("fila_compras", None),
                             ("fila_sigue", "plan"), ("fila_ahorro", None)):
            tira = getattr(self, clave)
            hijo = tira["contenido"].get_first_child()
            while hijo:
                sig = hijo.get_next_sibling()
                tira["contenido"].remove(hijo)
                hijo = sig
        for e in (d.get("enemigos") or []):
            nombre = str(e.get("heroe", "?"))
            almas = e.get("almas")
            if almas is None:
                texto = nombre.capitalize()
            else:
                kda = e.get("bajas")
                extra = (f" · {kda}/{e.get('muertes', 0)}/{e.get('asistencias', 0)}"
                         if kda is not None else "")
                texto = f"{nombre.capitalize()} · {almas:,}{extra}"
            self.fila_vs["contenido"].append(
                self._pill(texto, nombre.replace(" ", "_"), "heroes"))
        for c in (d.get("compras") or []):
            self.fila_compras["contenido"].append(
                self._pill(c.get("texto", ""), c.get("item"), "items"))
        for p in (d.get("plan") or []):
            self.fila_sigue["contenido"].append(self._pill(p["nombre"], p["id"], "items"))
        obj = d.get("objetivo")
        if obj:
            self.fila_ahorro["contenido"].append(
                self._pill(f"{obj['nombre']} · faltan {obj['faltan']:,}", obj["id"], "items"))

        # inventario
        hijo = self.inv.get_first_child()
        while hijo:
            sig = hijo.get_next_sibling()
            self.inv.remove(hijo)
            hijo = sig
        inv = d.get("inventario") or []
        for x in inv[:12]:
            caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            caja.add_css_class("slot")
            clase = "slot-bien" if (x.get("valor") or 0) >= 0 else "slot-mal"
            caja.add_css_class(clase)
            img = Gtk.Picture()
            img.set_size_request(52, 52)
            pb = cargar_icono(x["id"], "items", 52)
            if pb:
                img.set_pixbuf(pb)
            caja.append(img)
            if x.get("valor") is not None:
                v = Gtk.Label(label=f"{x['valor']:+.1f}".replace(".0", ""))
                v.add_css_class("val" if x["valor"] >= 0 else "val-mal")
                caja.append(v)
            self.inv.append(caja)
        for _ in range(max(0, 12 - len(inv))):
            vacio = Gtk.Box()
            vacio.add_css_class("slot"); vacio.add_css_class("slot-vacio")
            vacio.set_size_request(52, 52)
            self.inv.append(vacio)

        self.lbl_pie.set_label(
            f"motor {d.get('ms', '—')} ms · confianza {((d.get('confianza') or 1)*100):.0f}% · "
            f"{'lectura dudosa' if d.get('lectura_dudosa') else ('estable' if d.get('estable') else 'ajustando')}")


class App(Gtk.Application):
    def __init__(self, url):
        super().__init__(application_id="gg.diego.abramscoach")
        self.url = url

    def do_activate(self):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = Panel(self, self.url)
        win.present()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    a = ap.parse_args()
    App(a.url).run(None)


if __name__ == "__main__":
    sys.exit(main())
