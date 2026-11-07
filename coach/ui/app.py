#!/usr/bin/env python3
"""Ventana del Abrams Coach: una sola acción principal y el contexto alrededor.

Responsive de verdad, por ancho disponible (no por coordenadas fijas):

  < 760 px   una columna; VS y compras en una línea cada uno; plan oculto
  760-1100   dos columnas (principal + contexto)
  > 1100     tres columnas (principal, enemigos/plan, compras)

El tamaño y la posición se recuerdan en ~/.config/abrams-coach/ui.json.
Los datos llegan por `/api/estado` en un hilo aparte: la UI nunca bloquea el refresco.
"""
import hashlib
import json
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import preferencias
from .componentes.cabecera import Header
from .componentes.compras import PurchaseFeed
from .componentes.contra import ContraComposicion
from .componentes.enemigos import EnemyGrid
from .componentes.equipo import Equipo
from .componentes.inventario import Inventory
from .componentes.pie import StatusBar
from .componentes.plan import BuildPlan
from .componentes.recomendacion import RecommendationCard
from .componentes.tendencia import TrendChart
from .componentes.ventas import Ventas

ANCHO_ANGOSTO = 760
ANCHO_AMPLIO = 1100


def _leer_css():
    """CSS del paquete; si falta, el panel sigue con el tema del sistema."""
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tema.css")
    with open(ruta, "rb") as f:
        return f.read()


class Sondeo(threading.Thread):
    """Pide /api/estado cada segundo sin bloquear GTK.

    El panel anterior hacía `urlopen` dentro del bucle de GTK con timeout de 2 s: si el
    servidor tardaba, la ventana se quedaba congelada y dejaba de repintar.
    """

    def __init__(self, url, intervalo=1.0):
        super().__init__(daemon=True)
        self.url = url.rstrip("/") + "/api/estado"
        self.intervalo = intervalo
        self.lock = threading.Lock()
        self.datos = None
        self.error = None
        self.firma = None
        self.parar = False

    def run(self):
        while not self.parar:
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(self.url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as r:
                    datos = json.load(r)
                firma = hashlib.blake2b(
                    json.dumps(datos, sort_keys=True, default=str).encode(),
                    digest_size=8).hexdigest()
                with self.lock:
                    self.datos, self.error, self.firma = datos, None, firma
            except Exception as exc:                       # noqa: BLE001
                with self.lock:
                    self.error = str(exc)
            time.sleep(max(0.1, self.intervalo - (time.perf_counter() - t0)))

    def ultimo(self):
        with self.lock:
            return self.datos, self.error, self.firma


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app, url="http://127.0.0.1:8090", breakpoint="auto", intervalo=1.0,
                 tamano=None):
        prefs = preferencias.cargar()
        super().__init__(application=app, title="Abrams Coach")
        self.add_css_class("coach")
        self.url = url
        self.prefs = prefs
        self.forzado = None if breakpoint in (None, "auto") else breakpoint
        ancho, alto = tamano or (prefs["ancho"], prefs["alto"])
        self.set_default_size(int(ancho), int(alto))
        self.set_size_request(640, 480)
        if prefs.get("maximizado"):
            self.maximize()

        self.sondeo = Sondeo(url, intervalo)
        self.sondeo.start()

        self._modo = None
        self._firma = None
        self._construir()

        self.connect("close-request", self._al_cerrar)
        self.connect("notify::default-width", self._al_redimensionar)
        GLib.timeout_add(700, self._refrescar)

    # ------------------------------------------------------------------ construcción
    def _construir(self):
        self.raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for lado in ("top", "bottom", "start", "end"):
            getattr(self.raiz, f"set_margin_{lado}")(16)
        self.set_child(self.raiz)

        self.cabecera = Header()
        self.raiz.append(self.cabecera)

        # componentes (se reparten entre columnas según el ancho)
        self.recomendacion = RecommendationCard()
        self.inventario = Inventory()
        self.enemigos = EnemyGrid()
        self.compras = PurchaseFeed()
        self.plan = BuildPlan()
        self.tendencia = TrendChart()
        self.ventas = Ventas()
        self.equipo = Equipo()
        self.contra = ContraComposicion()
        self.pie = StatusBar()

        # el cuerpo va en un scrolled: si el monitor es 800×600 no se pierde nada
        self.desplazable = Gtk.ScrolledWindow()
        self.desplazable.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.desplazable.set_vexpand(True)
        self.cuerpo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.cuerpo.set_vexpand(True)
        self.cuerpo.set_valign(Gtk.Align.FILL)
        self.desplazable.set_child(self.cuerpo)
        self.raiz.append(self.desplazable)

        self.raiz.append(self.pie)

        self._atajos()
        self._aplicar_modo(self.forzado or self._modo_por_ancho(
            self.get_width() or self.prefs["ancho"]))

    def _seccion(self, rotulo, widget, clase_extra=""):
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if clase_extra:
            caja.add_css_class(clase_extra)
        if rotulo:
            from .componentes.base import etiqueta
            caja.append(etiqueta(rotulo, "rotulo"))
        caja.append(widget)
        return caja

    def _relleno(self):
        """Empuja el contenido hacia arriba cuando la ventana es más alta que el panel."""
        caja = Gtk.Box()
        caja.set_vexpand(True)
        return caja

    def _columna(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        col.set_hexpand(True)
        col.set_vexpand(True)
        col.set_valign(Gtk.Align.FILL)
        return col

    def _aplicar_modo(self, modo):
        """Reparte los componentes según el ancho. Solo se hace al cambiar de modo."""
        modo = modo or "angosto"
        if modo == self._modo:
            return
        self._modo = modo

        from .componentes.base import desacoplar, vaciar
        vaciar(self.cuerpo)
        for comp in (self.recomendacion, self.inventario, self.enemigos,
                     self.compras, self.plan, self.tendencia, self.ventas,
                     self.equipo, self.contra):
            desacoplar(comp)

        principal = self._columna()
        contexto = self._columna()
        lateral = self._columna()

        # Barra de 12 slots en una fila cuando hay ancho; 6×2 cuando no hay.
        self.inventario.set_lado(36 if modo == "angosto" else 44,
                                 columnas=6 if modo == "angosto" else 12)

        # La tarjeta manda pero no se estira: el alto que sobra va a la tendencia, que
        # aporta información. Una tarjeta vacía de 700 px no se lee.
        self.recomendacion.set_vexpand(False)
        # La tendencia no se estira: un gráfico de 700 px de alto no se lee. El espacio
        # que sobra se lo queda un relleno, y así el inventario no se va al fondo.
        self.tendencia.set_vexpand(True)
        self.tendencia.set_size_request(-1, 170)

        seccion_inv = self._seccion("INVENTARIO", self.inventario)
        seccion_enem = self._seccion("ENEMIGOS", self.enemigos)
        seccion_plan = self._seccion("PLAN", self.plan)
        seccion_comp = self._seccion("COMPRAS", self.compras)
        seccion_venta = self._seccion("VENTAS", self.ventas)
        seccion_equipo = self._seccion("EQUIPO", self.equipo)
        seccion_contra = self._seccion("CONTRA SU COMPOSICIÓN", self.contra)

        if modo == "angosto":
            principal.append(self.recomendacion)
            principal.append(self._seccion("INVENTARIO", self.inventario))
            principal.append(seccion_enem)
            principal.append(seccion_comp)
            principal.append(seccion_venta)
            principal.append(seccion_equipo)
            self.tendencia.set_visible(False)
            self.plan.set_visible(False)
            self.cuerpo.append(principal)
        elif modo == "medio":
            principal.append(self.recomendacion)
            principal.append(seccion_inv)
            principal.append(self._seccion("TENDENCIA DE ALMAS", self.tendencia))
            contexto.append(seccion_enem)
            contexto.append(seccion_plan)
            contexto.append(seccion_comp)
            contexto.append(self._relleno())
            contexto.append(seccion_venta)
            contexto.append(seccion_contra)
            contexto.append(seccion_equipo)
            self.tendencia.set_visible(True)
            self.plan.set_visible(True)
            contexto.set_size_request(300, -1)
            contexto.set_hexpand(False)
            self.cuerpo.append(principal)
            self.cuerpo.append(contexto)
        else:
            principal.append(self.recomendacion)
            principal.append(seccion_inv)
            principal.append(self._seccion("TENDENCIA DE ALMAS", self.tendencia))
            contexto.append(seccion_enem)
            contexto.append(seccion_plan)
            contexto.append(seccion_contra)
            contexto.append(seccion_equipo)
            lateral.append(seccion_comp)
            lateral.append(seccion_venta)
            lateral.append(self._relleno())
            self.tendencia.set_visible(True)
            self.plan.set_visible(True)
            contexto.set_size_request(300, -1)
            lateral.set_size_request(280, -1)
            contexto.set_hexpand(False)
            lateral.set_hexpand(False)
            self.cuerpo.append(principal)
            self.cuerpo.append(contexto)
            self.cuerpo.append(lateral)
        self.pie.set_visible(True)

    def _modo_por_ancho(self, ancho):
        ancho = int(ancho or 960)
        if ancho < ANCHO_ANGOSTO:
            return "angosto"
        if ancho < ANCHO_AMPLIO:
            return "medio"
        return "amplio"

    # ------------------------------------------------------------------ eventos
    def _ancho_actual(self):
        """Ancho real, con dos fuentes: `get_width()` es 0 hasta que la ventana se mapea."""
        ancho = self.get_width()
        if not ancho:
            ancho = self.get_default_size()[0] or 960
        return ancho

    def _al_redimensionar(self, *_):
        if self.forzado:
            return
        modo = self._modo_por_ancho(self._ancho_actual())
        if modo != self._modo:
            self._aplicar_modo(modo)

    def _al_cerrar(self, *_):
        ancho, alto = self.get_default_size()
        preferencias.guardar(ancho, alto, self.is_maximized(), None,
                             self.forzado or "auto")
        self.sondeo.parar = True
        return False

    def _atajos(self):
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._tecla)
        self.add_controller(ctrl)

    def _tecla(self, _c, tecla, _code, estado):
        nombre = Gdk.keyval_name(tecla) or ""
        if nombre in ("1", "KP_1"):
            self.recomendacion.grab_focus()
            return True
        if nombre in ("2", "KP_2"):
            self.enemigos.grab_focus()
            return True
        if nombre in ("3", "KP_3"):
            self.compras.grab_focus()
            return True
        if nombre in ("question", "questiondown"):
            self._ayuda()
            return True
        if nombre == "Escape":
            self.close()
            return True
        return False

    def _ayuda(self):
        dlg = Gtk.Window(transient_for=self, modal=True, title="Atajos")
        dlg.add_css_class("coach")
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for lado in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{lado}")(18)
        dlg.set_child(caja)
        from .componentes.base import etiqueta
        caja.append(etiqueta("Atajos", "t18"))
        for linea in ("1 · ir a la recomendación", "2 · ir a los enemigos",
                      "3 · ir a las compras", "? · esta ayuda", "Esc · cerrar"):
            caja.append(etiqueta(linea, "t13 tenue"))
        dlg.present()

    # ------------------------------------------------------------------ refresco
    def _refrescar(self):
        # El ancho definitivo no se conoce hasta que la ventana está mapeada: aquí se
        # corrige el breakpoint si hace falta (antes se quedaba en el de construcción).
        if not self.forzado:
            modo = self._modo_por_ancho(self._ancho_actual())
            if modo != self._modo:
                self._aplicar_modo(modo)
        datos, error, firma = self.sondeo.ultimo()
        if datos is None:
            self.cabecera.actualizar(None)
            self.pie.lbl_fuente.set_label(f"sin servidor ({error or 'sin datos'})"[:80])
            return True
        if firma == self._firma:
            return True                     # nada cambió: ni un repintado
        self._firma = firma
        try:
            self.cabecera.actualizar(datos)
            self.recomendacion.actualizar(datos)
            self.inventario.actualizar(datos)
            self.enemigos.actualizar(datos)
            self.compras.actualizar(datos)
            self.plan.actualizar(datos)
            self.tendencia.actualizar(datos)
            self.ventas.actualizar(datos)
            self.equipo.actualizar(datos)
            self.contra.actualizar(datos)
            self.pie.actualizar(datos)
        except Exception as exc:                           # noqa: BLE001
            self.pie.lbl_aviso.set_label(f"error de pintado: {exc}"[:90])
        return True


class App(Gtk.Application):
    def __init__(self, url="http://127.0.0.1:8090", breakpoint="auto", intervalo=1.0,
                 tamano=None):
        super().__init__(application_id="gg.diego.abramscoach")
        self.url = url
        self.breakpoint = breakpoint
        self.intervalo = intervalo
        self.tamano = tamano
        self._css = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        prov = Gtk.CssProvider()
        try:
            prov.load_from_data(_leer_css())
        except Exception:                                  # noqa: BLE001
            return
        self._css = prov
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = Panel(self, self.url, self.breakpoint, self.intervalo, self.tamano)
        win.present()
