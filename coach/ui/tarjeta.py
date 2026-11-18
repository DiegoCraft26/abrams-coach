"""Tarjeta mínima para mirar entre peleas, sin abrir el juego.

Qué es: un HTML de 420×160 px, autocontenido y sin CDN, con **solo** dos cosas:

    1. el siguiente objeto a comprar (icono grande, nombre y precio de lista);
    2. el camino de compra del momento, en 5 tiles con estado.

Nada de «faltan N», «te alcanza» ni ETA: las almas del broadcast llegan con 20-25 s de
retraso y el OCR no siempre las lee. El precio es el de lista porque ese sí es certeza;
si el estado está rancio, se dice cuántos segundos tiene.

Por qué: el panel nativo es una ventana grande y el jugador no la mira mientras juega.
Esta tarjeta está pensada para un navegador/OBS pequeño y se lee en dos segundos. El
servidor la renderiza ya con el último estado, y el JS la refresca cada segundo contra
`/api/estado`.

Honestidad: si no hay datos, si el coach no responde o si el estado está rancio, se ve
un estado vacío legible con el motivo. Nunca una pantalla negra, nunca un spinner
eterno y nunca un icono roto: si falta el PNG, quedan las iniciales del ítem.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote

ANCHO = 420
ALTO = 160

# Mismo umbral que `servidor.UMBRAL_RANCIO_S`. Se repite aquí para que la tarjeta
# también pueda renderizarse sola en pruebas o desde un archivo, sin importar el
# servidor (y sin crear un ciclo de imports).
UMBRAL_RANCIO_S = 8.0

_ESTADOS = {
    "tienes": "comprado",
    "comprado": "comprado",
    "hecho": "comprado",
    "ahora": "ahora",
    "actual": "ahora",
    "despues": "despues",
    "después": "despues",
}
_ETIQUETAS = {"comprado": "COMPRADO", "ahora": "AHORA", "despues": "DESPUÉS"}


def iniciales(nombre):
    """Iniciales para el marcador cuando no hay icono: «Weighted Shots» -> «WS»."""
    palabras = re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", str(nombre or ""))
    if not palabras:
        return "?"
    if len(palabras) == 1:
        return palabras[0][:2].upper()
    return (palabras[0][0] + palabras[1][0]).upper()


def _num(valor):
    """Número finito o None. Acepta strings con coma de miles; nunca lanza."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return valor if valor == valor and abs(valor) != float("inf") else None
    try:
        numero = float(str(valor).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return numero if numero == numero and abs(numero) != float("inf") else None


def _entero(valor):
    numero = _num(valor)
    return int(numero) if numero is not None else None


def _fmt(valor):
    numero = _entero(valor)
    return f"{numero:,}" if numero is not None else None


def _texto(valor, defecto=""):
    return defecto if valor is None else str(valor)


def _dict(valor):
    return valor if isinstance(valor, dict) else {}


def _lista_dicts(valor):
    if not isinstance(valor, list):
        return []
    return [x for x in valor if isinstance(x, dict)]


def _estado(valor):
    return _ESTADOS.get(str(valor or "").strip().lower(), "despues")


def _etiqueta_estado(estado):
    return _ETIQUETAS.get(estado, "·")


def _icono(iid, nombre, clase):
    """Icono con marcador de iniciales debajo. El PNG sólo se muestra si carga.

    El `onerror` quita la imagen en vez de dejarla rota; las iniciales ya están en el
    DOM y quedan visibles. Lo mismo vale para la foto grande y para los tiles.
    """
    marca = html.escape(iniciales(nombre))
    img = ""
    if iid is not None and str(iid) != "":
        src = "/icono/" + quote(str(iid), safe="")
        img = (f'<img src="{src}" alt="" loading="eager" '
               f"onload=\"this.parentNode.classList.add('cargado')\" "
               f"onerror=\"this.remove()\">")
    return f'<div class="{clase}"><span class="iniciales">{marca}</span>{img}</div>'


def _tile(paso):
    """Un tile es icono + estado. El nombre completo vive solo en la cabecera.

    Dejar el nombre aquí obligaba a recortarlo con puntos suspensivos («Bullet Resi…»)
    y en una tarjeta de 2 s eso se lee como un error. Si falta el icono, las iniciales
    van centradas en el hueco del icono.
    """
    p = _dict(paso)
    if not p:
        return ('<div class="tile vacio" title="sin datos">'
                '<div class="mini"><span class="iniciales">·</span></div>'
                '<div class="s">·</div></div>')
    estado = _estado(p.get("estado"))
    etiqueta = _etiqueta_estado(estado)
    return (f'<div class="tile {estado}" title="{etiqueta}">'
            f'{_icono(p.get("id"), p.get("nombre"), "mini")}'
            f'<div class="s">{etiqueta}</div></div>')


def _tiles(camino):
    """Siempre 5 huecos: los que falten se ven como guiones, no como un error."""
    pasos = _lista_dicts(camino)[:5]
    return "".join(_tile(pasos[i]) if i < len(pasos) else _tile(None)
                   for i in range(5))


def _aviso(d, rancio):
    """Solo se habla del tiempo cuando el dato está viejo.

    Nada de «faltan N» ni «te alcanza»: las almas del broadcast llegan con 20-25 s de
    retraso y el OCR no siempre las lee. La tarjeta enseña lo que sí es certeza.
    """
    if not rancio:
        return ""
    edad = _entero(d.get("edad_s"))
    texto = f"datos de hace {edad} s" if edad is not None else "datos viejos"
    motivo = ("último estado guardado" if d.get("origen") == "guardado"
              else "el coach no publica desde entonces")
    return (f'<span class="aviso" title="{html.escape(motivo, quote=True)}">'
            f"{html.escape(texto)}</span>")


def _cuerpo(datos, edad):
    d = _dict(datos)
    recs = _lista_dicts(d.get("recomendaciones"))
    rec = recs[0] if recs and (recs[0].get("nombre") or recs[0].get("id")) else None
    decision = _dict(d.get("decision"))

    camino = _lista_dicts(d.get("camino"))[:5]
    if not camino:
        camino = _lista_dicts(decision.get("camino"))[:5]
    if not camino:
        # Respaldo: el plan de dos compras de siempre, con el primero como «ahora».
        plan = _lista_dicts(d.get("plan"))[:5]
        camino = [{**p, "estado": "ahora" if i == 0 else "despues"}
                  for i, p in enumerate(plan)]

    # El ítem grande es el objetivo de la decisión (el paso «ahora» del camino), no
    # `recomendaciones[0]`: el ranking y el camino pueden apuntar a cosas distintas y
    # dos nombres para la misma compra en una tarjeta de 2 s es ruido. Si no hay
    # objetivo, se usa el ítem de la decisión, el primer «ahora» del camino y, al
    # final, la recomendación.
    item = _dict(decision.get("objetivo"))
    if not (item.get("nombre") or item.get("id")):
        item = _dict(decision.get("item"))
    if not (item.get("nombre") or item.get("id")):
        item = next((p for p in camino
                     if _estado(p.get("estado")) == "ahora"), None)
        item = _dict(item)
    if not (item.get("nombre") or item.get("id")):
        item = rec

    rancio = bool(d.get("rancio"))
    if (not rancio and isinstance(edad, (int, float)) and not isinstance(edad, bool)
            and edad > UMBRAL_RANCIO_S):
        rancio = True
    if rancio and d.get("edad_s") is None and isinstance(edad, (int, float)):
        d = {**d, "edad_s": round(float(edad), 1)}

    if item is None:
        if not d:
            eyebrow, titulo, detalle = "SIN COACH", "Sin coach", "todavía no hay datos"
        elif rancio:
            eyebrow, titulo, detalle = ("ÚLTIMO DATO", "Sin datos frescos",
                                        "el coach dejó de publicar")
        elif d.get("listo") is False:
            eyebrow = "SIN PARTIDA"
            titulo = "Esperando partida"
            detalle = "aún no hay datos del coach"
        elif str(decision.get("modo") or "") == "completo":
            eyebrow, titulo, detalle = ("SIN COMPRA", "Build completo",
                                        "no queda nada en el camino")
        else:
            eyebrow, titulo, detalle = ("SIN COMPRA", "Sin compra ahora",
                                        "el motor no tiene una compra para este momento")
        cabecera = (
            '<div class="cabecera"><div class="icono vacio">'
            '<span class="iniciales">—</span></div>'
            '<div class="texto"><div class="linea">'
            f'<span class="etiqueta">{html.escape(eyebrow)}</span>'
            f'{_aviso(d, rancio)}'
            '</div>'
            f'<div class="nombre">{html.escape(titulo)}</div>'
            f'<div class="precio"><span class="detalle">{html.escape(detalle)}</span></div>'
            '</div></div>'
        )
        clase = "tarjeta vacia" + (" rancio" if rancio else "")
        return (f'<div id="tarjeta" class="{clase}">{cabecera}'
                f'<div class="camino">{_tiles(camino)}</div></div>')

    nombre = _texto(item.get("nombre"), "—")
    costo = _entero(item.get("costo_lista"))
    if costo is None or costo <= 0:
        costo = _entero(item.get("costo"))
    if (costo is None or costo <= 0) and rec is not None:
        costo = _entero(rec.get("costo_lista"))
        if costo is None or costo <= 0:
            costo = _entero(rec.get("costo"))
    precio = f"{_fmt(costo)} oro" if costo is not None and costo > 0 else "—"

    cabecera = (
        f'<div class="cabecera">{_icono(item.get("id"), nombre, "icono")}'
        '<div class="texto">'
        f'<div class="linea">{_aviso(d, rancio)}</div>'
        f'<div class="nombre" title="{html.escape(nombre, quote=True)}">'
        f'{html.escape(nombre)}</div>'
        '<div class="precio" title="precio de lista">'
        f'<span class="oro">{html.escape(precio)}</span></div>'
        '</div></div>'
    )
    clase = "tarjeta" + (" rancio" if rancio else "")
    return (f'<div id="tarjeta" class="{clase}">{cabecera}'
            f'<div class="camino">{_tiles(camino)}</div></div>')


def pagina(datos=None, edad=None):
    """HTML completo con el último estado ya pintado.

    `datos` es el mismo payload de `/api/estado`; `edad` son los segundos desde la
    última publicación. La función nunca lanza: cualquier forma rara cae en el estado
    vacío, que es preferible a un 500 en la tarjeta.
    """
    return _INICIO + _CSS + _MEDIO + _cuerpo(datos, edad) + _SCRIPT + _JS + _FIN


_INICIO = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Abrams Coach · tarjeta</title>
<style>
"""

_CSS = """
:root{
  --bg:#0A0C10; --surface:#141821; --surface-2:#1B2029;
  --line:#232936; --line-2:#2B3342;
  --fg:#E8ECF3; --fg-2:#B7C0CE; --fg-3:#8B95A5;
  --ok:#5FD08A; --warn:#F2B544; --bad:#EF6B6B; --gold:#E9C46A;
  --stack:"Inter", "Segoe UI Variable", "Segoe UI", system-ui, Roboto, sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;background:var(--bg);overflow:hidden}
body{
  display:grid;place-items:center;color:var(--fg);
  font:14px/1.2 var(--stack);-webkit-font-smoothing:antialiased;color-scheme:dark;
  font-optical-sizing:auto;text-rendering:optimizeLegibility;
}
.tarjeta{
  width:420px;height:160px;max-width:100vw;max-height:100vh;
  display:grid;grid-template-rows:82px 48px;gap:8px;
  padding:9px 11px;background:var(--surface);
  border:1px solid var(--line);border-radius:14px;overflow:hidden;
}
.cabecera{
  display:grid;grid-template-columns:82px minmax(0,1fr);gap:12px;
  align-items:center;min-width:0;
}
.icono,.mini{
  position:relative;display:grid;place-items:center;overflow:hidden;
  background:#0B0D11;border:1px solid var(--line-2);
}
.icono{width:82px;height:82px;border-radius:12px}
.mini{width:28px;height:28px;border-radius:7px;flex:0 0 auto}
.icono img,.mini img{display:none;width:100%;height:100%;object-fit:cover}
.icono.cargado img,.mini.cargado img{display:block}
.icono.cargado .iniciales,.mini.cargado .iniciales{display:none}
.iniciales{font-weight:900;color:var(--fg-3);letter-spacing:.04em;line-height:1}
.icono .iniciales{font-size:27px}
.mini .iniciales{font-size:10px}
.icono.vacio .iniciales{font-size:30px}
.texto{min-width:0;display:flex;flex-direction:column;justify-content:center;gap:2px}
.linea{display:flex;align-items:center;justify-content:flex-end;gap:6px;min-width:0}
.tarjeta.vacia .linea{justify-content:flex-start}
.etiqueta{
  font-size:9.5px;font-weight:900;letter-spacing:.14em;color:var(--ok);
  white-space:nowrap;text-transform:uppercase;
}
.tarjeta.vacia .etiqueta{color:var(--fg-3)}
.tarjeta.rancio .etiqueta{color:var(--warn)}
.aviso{
  margin-left:auto;font-size:9px;font-weight:700;color:var(--warn);
  border:1px solid rgba(242,181,68,.4);background:rgba(242,181,68,.1);
  border-radius:999px;padding:1px 6px;white-space:nowrap;
}
.nombre{
  font-size:22px;font-weight:700;line-height:1.06;color:var(--fg);
  white-space:normal;overflow-wrap:anywhere;letter-spacing:-.015em;
  font-optical-sizing:auto;
}
.tarjeta.vacia .nombre{font-size:20px;color:var(--fg-2)}
.precio{
  font-size:13.5px;font-weight:700;font-variant-numeric:tabular-nums;
  font-feature-settings:"tnum" 1;white-space:nowrap;
}
.precio .oro{color:var(--gold)}
.precio .sep{color:var(--fg-3)}
.precio .detalle{color:var(--fg-2);font-weight:600}
.tarjeta.vacia .precio{
  font-size:11px;font-weight:500;white-space:normal;line-height:1.2;
  max-height:2.4em;overflow:hidden;
}
.camino{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;min-height:0}
.tile{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:3px;padding:3px;border:1px solid var(--line);border-radius:8px;
  background:#10141C;min-width:0;overflow:hidden;
}
.tile .s{
  font-size:8px;font-weight:800;letter-spacing:.08em;line-height:1;
  color:var(--fg-3);text-transform:uppercase;
}
.tile.ahora{
  border-color:var(--ok);background:rgba(95,208,138,.10);
  box-shadow:inset 0 0 0 1px rgba(95,208,138,.18);
}
.tile.ahora .s{color:var(--ok)}
.tile.comprado{opacity:.55}
.tile.comprado .s{color:var(--ok)}
.tile.despues{opacity:.9}
.tile.vacio{border-style:dashed;opacity:.45}
.tarjeta.rancio .cabecera,.tarjeta.rancio .camino{opacity:.72}
@media (prefers-reduced-motion: no-preference){
  .tile{transition:border-color .18s,background-color .18s,opacity .18s}
}
"""

_MEDIO = """</style>
</head>
<body>
"""

_SCRIPT = """
<script>
"""

_JS = """
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const nf = new Intl.NumberFormat("es-MX");
  const esc = (s) => String(s ?? "").replace(/[<>&"']/g, (c) => ({
    "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const num = (v) => {
    if (typeof v === "number") return Number.isFinite(v) ? v : null;
    if (typeof v === "string" && v.trim() !== "") {
      const n = Number(v.replace(/,/g, ""));
      return Number.isFinite(n) ? n : null;
    }
    return null;
  };
  const iniciales = (nombre) => {
    const palabras = String(nombre || "").match(/[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+/g) || [];
    if (!palabras.length) return "?";
    if (palabras.length === 1) return palabras[0].slice(0, 2).toUpperCase();
    return (palabras[0][0] + palabras[1][0]).toUpperCase();
  };
  const icono = (id, nombre, clase) => {
    const img = (id !== null && id !== undefined && String(id) !== "")
      ? `<img src="/icono/${encodeURIComponent(String(id))}" alt="" loading="eager" onload="this.parentNode.classList.add('cargado')" onerror="this.remove()">`
      : "";
    return `<div class="${clase}"><span class="iniciales">${esc(iniciales(nombre))}</span>${img}</div>`;
  };
  const ESTADOS = {
    tienes: "comprado", comprado: "comprado", hecho: "comprado",
    ahora: "ahora", actual: "ahora",
    despues: "despues", "después": "despues",
  };
  const etiquetaEstado = (e) => e === "comprado" ? "COMPRADO"
    : e === "ahora" ? "AHORA" : e === "despues" ? "DESPUÉS" : "·";
  const tile = (p) => {
    const estado = ESTADOS[String(p?.estado ?? "").toLowerCase()] || "despues";
    const etiqueta = etiquetaEstado(estado);
    return `<div class="tile ${estado}" title="${etiqueta}">${icono(p?.id, p?.nombre, "mini")}<div class="s">${etiqueta}</div></div>`;
  };
  const tileVacio = () => '<div class="tile vacio" title="sin datos"><div class="mini"><span class="iniciales">·</span></div><div class="s">·</div></div>';
  const tiles = (camino) => {
    const pasos = Array.isArray(camino) ? camino.slice(0, 5) : [];
    let html = "";
    for (let i = 0; i < 5; i++) {
      const p = pasos[i];
      html += p && typeof p === "object" ? tile(p) : tileVacio();
    }
    return html;
  };
  const caminoDe = (d) => {
    if (Array.isArray(d?.camino) && d.camino.length) return d.camino;
    if (Array.isArray(d?.decision?.camino) && d.decision.camino.length) return d.decision.camino;
    if (Array.isArray(d?.plan)) return d.plan.map((p, i) => ({
      ...p, estado: i === 0 ? "ahora" : "despues",
    }));
    return [];
  };
  const activarIconos = (raiz) => {
    raiz.querySelectorAll(".icono img, .mini img").forEach((img) => {
      if (img.complete && img.naturalWidth > 0) img.parentNode.classList.add("cargado");
    });
  };
  /* La cabecera nunca recorta: prueba 22 -> 20 -> 18 -> 16 px y, si aun así no cabe,
     parte el nombre en dos líneas. Sin recortes ni puntos suspensivos. */
  const ajustarNombre = (raiz) => {
    const el = raiz.querySelector(".nombre");
    if (!el) return;
    const pasos = raiz.classList.contains("vacia") ? [20, 18, 16] : [22, 20, 18, 16];
    const rango = document.createRange();
    // 8 px de aire: «cabe justo» también se ve mal al lado del borde.
    const disponible = el.clientWidth - 8;
    el.style.whiteSpace = "nowrap";
    el.style.overflowWrap = "normal";
    for (const px of pasos) {
      el.style.fontSize = `${px}px`;
      rango.selectNodeContents(el);
      if (rango.getBoundingClientRect().width <= disponible) return;
    }
    el.style.whiteSpace = "normal";
    el.style.overflowWrap = "anywhere";
    el.style.fontSize = "16px";
  };
  const avisoTexto = (d) => {
    if (!d || !d.rancio) return "";
    const e = num(d.edad_s);
    return e !== null ? `datos de hace ${Math.round(e)} s` : "datos viejos";
  };
  const avisoTitle = (d) => d?.origen === "guardado"
    ? "último estado guardado" : "el coach no publica desde entonces";
  const avisoHtml = (d) => {
    const t = avisoTexto(d);
    return t ? `<span class="aviso" title="${esc(avisoTitle(d))}">${esc(t)}</span>` : "";
  };
  const actualizarAviso = (d) => {
    const tarjeta = $("tarjeta");
    if (!tarjeta) return;
    tarjeta.classList.toggle("rancio", Boolean(d?.rancio));
    const linea = tarjeta.querySelector(".linea");
    if (!linea) return;
    const t = avisoTexto(d);
    let aviso = linea.querySelector(".aviso");
    if (!t) {
      if (aviso) aviso.remove();
      return;
    }
    if (!aviso) {
      aviso = document.createElement("span");
      aviso.className = "aviso";
      linea.appendChild(aviso);
    }
    aviso.textContent = t;
    aviso.title = avisoTitle(d);
  };
  const vacia = (eyebrow, titulo, detalle, d) => {
    const tarjeta = $("tarjeta");
    if (!tarjeta) return;
    tarjeta.className = "tarjeta vacia" + (d?.rancio ? " rancio" : "");
    tarjeta.innerHTML = `<div class="cabecera"><div class="icono vacio"><span class="iniciales">—</span></div><div class="texto"><div class="linea"><span class="etiqueta">${esc(eyebrow)}</span>${d?.rancio ? avisoHtml(d) : ""}</div><div class="nombre">${esc(titulo)}</div><div class="precio"><span class="detalle">${esc(detalle)}</span></div></div></div><div class="camino">${tiles(caminoDe(d || {}))}</div>`;
    activarIconos(tarjeta);
    ajustarNombre(tarjeta);
  };
  const pintar = (d) => {
    const tarjeta = $("tarjeta");
    if (!tarjeta) return;
    d = d && typeof d === "object" ? d : {};
    const decision = d.decision && typeof d.decision === "object" ? d.decision : {};
    const recs = Array.isArray(d.recomendaciones)
      ? d.recomendaciones.filter((x) => x && typeof x === "object") : [];
    const rec = recs[0] || null;
    if (!rec) {
      if (!Object.keys(d).length) {
        vacia("SIN COACH", "Sin coach", "todavía no hay datos", d);
      } else if (d.listo === false) {
        vacia("SIN PARTIDA", "Esperando partida",
          "aún no hay datos del coach", d);
      } else if (decision.modo === "completo") {
        vacia("SIN COMPRA", "Build completo", "no queda nada en el camino", d);
      } else {
        vacia("SIN COMPRA", "Sin compra ahora",
          "el motor no tiene una compra para este momento", d);
      }
      return;
    }
    const camino = caminoDe(d);
    let item = decision.objetivo && typeof decision.objetivo === "object"
      ? decision.objetivo : null;
    if (!item || (!item.nombre && !item.id)) {
      item = decision.item && typeof decision.item === "object" ? decision.item : null;
    }
    if (!item || (!item.nombre && !item.id)) {
      item = camino.find((p) => ESTADOS[String(p?.estado ?? "").toLowerCase()] === "ahora") || rec;
    }
    const nombre = String(item?.nombre ?? "—");
    let costo = num(item?.costo_lista) ?? num(rec.costo_lista);
    if (costo === null || costo <= 0) costo = num(item?.costo) ?? num(rec.costo);
    const precio = costo !== null && costo > 0 ? `${nf.format(costo)} oro` : "—";
    tarjeta.className = "tarjeta" + (d.rancio ? " rancio" : "");
    tarjeta.innerHTML = `<div class="cabecera">${icono(item?.id, nombre, "icono")}<div class="texto"><div class="linea">${avisoHtml(d)}</div><div class="nombre" title="${esc(nombre)}">${esc(nombre)}</div><div class="precio" title="precio de lista"><span class="oro">${esc(precio)}</span></div></div></div><div class="camino">${tiles(camino)}</div>`;
    activarIconos(tarjeta);
    ajustarNombre(tarjeta);
  };
  const firma = (d) => {
    const rec = Array.isArray(d?.recomendaciones) ? d.recomendaciones[0] : null;
    const obj = d?.decision?.objetivo || null;
    const it = d?.decision?.item || null;
    return JSON.stringify({
      id: rec?.id ?? null, nombre: rec?.nombre ?? null,
      costo: rec?.costo_lista ?? rec?.costo ?? null,
      objetivo: obj?.id ?? null,
      objetivo_costo: obj?.costo_lista ?? obj?.costo ?? null,
      item: it?.id ?? null,
      item_costo: it?.costo_lista ?? it?.costo ?? null,
      listo: d?.listo ?? null, rancio: Boolean(d?.rancio),
      modo: d?.decision?.modo ?? null,
      camino: caminoDe(d || {}).slice(0, 5).map((p) => [
        p?.id ?? null, p?.nombre ?? null, p?.costo ?? null, p?.estado ?? null,
      ]),
    });
  };
  let _firma = null, _fallos = 0, _visto = false, _sinCoach = false;
  const latir = async () => {
    try {
      const r = await fetch("/api/estado", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _fallos = 0;
      _sinCoach = false;
      const f = firma(d);
      if (f !== _firma) {
        _firma = f;
        pintar(d);
        _visto = true;
      } else {
        actualizarAviso(d);
      }
    } catch (e) {
      _fallos += 1;
      if (!_sinCoach && (_fallos >= 2 || (_fallos === 1 && !_visto))) {
        _sinCoach = true;
        _firma = null;
        _visto = false;
        vacia("SIN COACH", "Sin coach", "no responde · reintentando cada segundo", {});
      }
    }
  };
  latir();
  setInterval(latir, 1000);
})();
"""

_FIN = """
</script>
</body>
</html>
"""
