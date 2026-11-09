#!/usr/bin/env python3
"""Ventana del Abrams Coach: una sola acción principal y el contexto alrededor.

Responsive de verdad, por ancho disponible (no por coordenadas fijas):

  < 1000 px  una columna; tarjeta de acción y camino arriba
  1000-1359  dos columnas (acción/camino/inventario + enemigos)
  >= 1360    tres columnas (principal, contexto y lateral)

El tamaño y la posición se recuerdan en ~/.config/abrams-coach/ui.json.
Los datos llegan por `/api/estado` en un hilo aparte: la UI nunca bloquea el refresco.
"""
import hashlib
import json
import threading
import time
import urllib.request
from urllib.parse import urlparse

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
from .componentes.revisar import Revisar
from .componentes.tendencia import TrendChart
from .componentes.ventas import Ventas

# Umbrales por ancho real: la tarjeta mide como mucho 640 y la columna de contexto
# pide 300. Por debajo de 1,000 no caben las dos sin pisarse; las tres columnas
# necesitan 640 + 300 + 280 + separaciones.
ANCHO_ANGOSTO = 1000
ANCHO_AMPLIO = 1360
ALTO_COMPACTO = 720      # por debajo de esto se ocultan las secciones secundarias


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
        self._ver_secundarias = False
        self._construir()

        self.connect("close-request", self._al_cerrar)
        self.connect("notify::default-width", self._al_redimensionar)
        GLib.timeout_add(700, self._refrescar)

    # ------------------------------------------------------------------ construcción
    def _construir(self):
        self.raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for lado in ("top", "bottom", "start", "end"):
            getattr(self.raiz, f"set_margin_{lado}")(12)
        self.set_child(self.raiz)

        self.cabecera = Header()
        self.raiz.append(self.cabecera)

        # componentes (se reparten entre columnas según el ancho)
        self.recomendacion = RecommendationCard()
        self.recomendacion.actualizar({"listo": False, "mensaje": "conectando al coach"})
        self.inventario = Inventory()
        self.enemigos = EnemyGrid()
        self.compras = PurchaseFeed()
        self.plan = BuildPlan()
        self.tendencia = TrendChart()
        self.ventas = Ventas()
        self.equipo = Equipo()
        self.contra = ContraComposicion()
        # Botón de diagnóstico: pregunta a /api/revisar y pinta lo que devuelva el
        # servidor, sin inventar nada. El puerto sale de la URL del panel.
        try:
            puerto = int(urlparse(self.url).port or 8090)
        except Exception:                                  # noqa: BLE001
            puerto = 8090
        self.revisar = Revisar(puerto=puerto)
        self.pie = StatusBar()

        # el cuerpo va en un scrolled: si el monitor es 800×600 no se pierde nada
        self.desplazable = Gtk.ScrolledWindow()
        self.desplazable.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.desplazable.set_vexpand(True)
        self.cuerpo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.cuerpo.set_vexpand(True)
        self.cuerpo.set_valign(Gtk.Align.FILL)
        # El panel se usa en un segundo monitor: el contenido se centra en vez de
        # quedarse pegado a la izquierda en un 1440p.
        self.cuerpo.set_halign(Gtk.Align.CENTER)
        self.desplazable.set_child(self.cuerpo)
        self.raiz.append(self.desplazable)

        self.barra_pie = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pie.set_hexpand(True)
        self.barra_pie.append(self.pie)
        self.boton_mas = Gtk.ToggleButton(label="Más")
        self.boton_mas.add_css_class("boton")
        self.boton_mas.set_tooltip_text("Tendencia, compras, ventas, equipo y composición")
        self.boton_mas.connect("toggled", self._al_toggle_mas)
        self.barra_pie.append(self.boton_mas)
        self.raiz.append(self.barra_pie)

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

    def _es_compacto(self):
        alto = self.get_height() or (self.get_default_size()[1] if self.get_default_size() else 0)
        return bool(alto and alto < ALTO_COMPACTO)

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
        if modo == self._modo and getattr(self, "_compacto", None) == self._es_compacto():
            return
        self._modo = modo
        self._compacto = self._es_compacto()

        from .componentes.base import desacoplar, vaciar
        vaciar(self.cuerpo)
        for comp in (self.recomendacion, self.inventario, self.enemigos,
                     self.compras, self.plan, self.tendencia, self.ventas,
                     self.equipo, self.contra, self.revisar):
            desacoplar(comp)

        principal = self._columna()
        # La columna principal no se come el ancho sobrante: la tarjeta mide 640 y el
        # contexto va pegado a ella, no empujado al borde del monitor.
        principal.set_hexpand(False)
        contexto = self._columna()
        lateral = self._columna()

        # Barra de slots: 12 en fila solo cuando hay ancho de verdad (>1100); a
        # 1280x720 la columna mide ~640 px y 12 celdas partían el inventario en filas
        # irregulares de 10+2. QA de UI, 2026-11-08.
        ancho = modo == "amplio"
        self.inventario.set_lado(36 if modo == "angosto" else 44,
                                 columnas=12 if ancho else 6)

        # La tarjeta manda, no se estira y no pasa de 640 px en columnas anchas.
        self.recomendacion.set_vexpand(False)
        self.recomendacion.limitar(640 if self._ancho_actual() >= 700 else None)
        # La tendencia NO se estira: con vexpand se comía ~630 px de alto a 1920x1080
        # para dos polilíneas (medido en QA). Alto fijo y el sobrante va a un relleno.
        self.tendencia.set_vexpand(False)
        self.tendencia.set_size_request(-1, 170)

        seccion_inv = self._seccion("INVENTARIO", self.inventario)
        seccion_enem = self._seccion("ENEMIGOS", self.enemigos)
        seccion_plan = self._seccion("CAMINO", self.plan)
        seccion_comp = self._seccion("COMPRAS", self.compras)
        seccion_venta = self._seccion("VENTAS", self.ventas)
        seccion_equipo = self._seccion("TU EQUIPO", self.equipo)
        seccion_contra = self._seccion("CONTRA SU COMPOSICIÓN", self.contra)
        seccion_tend = self._seccion("TENDENCIA DE ALMAS", self.tendencia)
        seccion_revisar = self._seccion("¿ALGO VA MAL?", self.revisar)

        # Las secundarias nacen plegadas: el panel enseña una acción y el camino; el
        # resto se abre con «Más». Con la ventana baja se quedan plegadas aunque el
        # botón esté activo, para no cortar frases a media altura.
        self._secundarias = [seccion_tend, seccion_comp, seccion_venta,
                             seccion_equipo, seccion_contra]

        if modo == "angosto":
            principal.append(self.recomendacion)
            principal.append(seccion_plan)
            principal.append(seccion_inv)
            principal.append(seccion_enem)
            principal.append(seccion_revisar)
            for seccion in self._secundarias:
                principal.append(seccion)
            self.cuerpo.append(principal)
        elif modo == "medio":
            principal.append(self.recomendacion)
            principal.append(seccion_plan)
            principal.append(seccion_inv)
            principal.append(seccion_tend)
            contexto.append(seccion_enem)
            contexto.append(seccion_comp)
            contexto.append(seccion_venta)
            contexto.append(seccion_contra)
            contexto.append(seccion_equipo)
            contexto.append(seccion_revisar)
            contexto.set_size_request(300, -1)
            contexto.set_hexpand(False)
            self.cuerpo.append(principal)
            self.cuerpo.append(contexto)
        else:
            principal.append(self.recomendacion)
            principal.append(seccion_plan)
            principal.append(seccion_inv)
            principal.append(seccion_tend)
            contexto.append(seccion_enem)
            contexto.append(seccion_contra)
            contexto.append(seccion_equipo)
            lateral.append(seccion_comp)
            lateral.append(seccion_venta)
            lateral.append(seccion_revisar)
            lateral.append(self._relleno())
            contexto.set_size_request(300, -1)
            lateral.set_size_request(280, -1)
            contexto.set_hexpand(False)
            lateral.set_hexpand(False)
            self.cuerpo.append(principal)
            self.cuerpo.append(contexto)
            self.cuerpo.append(lateral)

        self._aplicar_visibilidad()
        self.pie.set_visible(True)

    def _aplicar_visibilidad(self):
        mostrar = self._ver_secundarias and not self._es_compacto()
        for seccion in getattr(self, "_secundarias", []):
            seccion.set_visible(mostrar)

    def _al_toggle_mas(self, boton):
        self._ver_secundarias = bool(boton.get_active())
        self._aplicar_visibilidad()

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
        caja.append(etiqueta("Atajos", "t20"))
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
            elif self._es_compacto() != self._compacto:
                # cambió el alto: se recompone para no dejar secciones cortadas
                self._compacto = self._es_compacto()
                self._aplicar_modo(None)
        datos, error, firma = self.sondeo.ultimo()
        if datos is None:
            self.cabecera.actualizar(None)
            # La tarjeta nace con su estado vacío compacto; sin esto se quedaba con
            # el alto de construcción (190 px) aunque no hubiera servidor.
            self.recomendacion.actualizar(
                {"listo": False, "mensaje": "sin servidor del coach: arráncalo con "
                                            "«abrams-coach demo» o «abrams-coach jugar»"})
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
