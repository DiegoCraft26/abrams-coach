"""Panel web: la misma información que la app nativa, sin instalar nada.

Por qué: la app nativa es GTK y vive en esta máquina (130 MB y un proceso más). Con el
panel web el coach sigue leyendo aquí, pero el panel puede abrirse en cualquier navegador
—incluso desde la otra PC por LAN— y no cuesta un proceso extra.

Contrato de información (auditoría de UI 2026-11-18 + departamento D5). El jugador mira
este panel 2-3 segundos entre peleas; cada zona tiene que ganarse el sitio con una
decisión concreta, y nada más entra:

    1. estado de la lectura     ¿puedo confiar en lo que veo? (en vivo / hace N s / solo pantalla)
    2. ítem a comprar           la única acción: QUÉ compro
    3. precio de lista          ¿cuánto cuesta? (sin «faltan»: el oro llega tarde)
    4. venta                    ¿qué suelto para hacer sitio? (solo si aplica)
    5. amenaza                  a quién no buscar solo (solo si aplica)
    6. evidencia                efecto con intervalo y n (solo si existe y no es ruido)
    7. inventario               solo si hay una venta o un desajuste de lectura

Fuera: el reloj y el oro a 22 px (el juego ya los muestra en pantalla y duplicarlos
gastaba la mirada), la lista del plan de 6 filas, el roster de 12 jugadores, las tres
frases libres del pie y la lista de ventas repetida.

No usa recursos externos: ni fuentes, ni CDN, ni frameworks. Un HTML con su CSS y su JS
inline que consulta `/api/estado` cada segundo. Si el coach deja de publicar, se ve el
aviso de datos viejos en vez de números congelados sin decirlo.
"""

PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Abrams Coach</title>
<style>
  /* Tokens con rol, no con hex suelto: los mismos valores que tema.css del panel GTK,
     para que sean el mismo producto y no dos primos con paletas parecidas. */
  :root{
    /* Valores copiados de coach/ui/tema.css (la única fuente de verdad del tema):
       si cambian allí, el test de contrato obliga a cambiarlos aquí. */
    --bg:#0A0C10; --surface:#141821; --surface-2:#1B2029;
    --line:#232936; --line-2:#2B3342;
    --fg:#E8ECF3; --fg-2:#B7C0CE; --fg-3:#8B95A5;
    --ok:#5FD08A; --warn:#F2B544; --bad:#EF6B6B; --info:#7FB6F2; --gold:#E9C46A;
    --ok-bg:rgba(95,208,138,.12); --warn-bg:rgba(242,181,68,.12);
    --bad-bg:rgba(239,107,107,.12);
    /* Rampa de tres tamaños. Cinco tamaños para siete zonas es ruido tipográfico. */
    --t-xs:12px; --t-sm:14px; --t-lg:20px; --t-xl:30px;
    --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
    --r1:6px; --r2:10px; --r3:999px;
    --stack:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;
  }
  * { box-sizing: border-box; }
  html{ color-scheme: dark }
  body{
    margin:0; min-height:100dvh; display:grid; grid-template-rows:auto 1fr auto;
    background:var(--bg); color:var(--fg);
    font:var(--t-sm)/1.45 var(--stack);
  }
  header{
    position:sticky; top:0; z-index:2; display:flex; align-items:center;
    gap:var(--s3); padding:var(--s3) var(--s4); flex-wrap:wrap;
    background:var(--surface); border-bottom:1px solid var(--line);
  }
  header .hud{ margin-left:auto; display:flex; gap:var(--s2); align-items:center }
  .chip { border:1px solid var(--line); border-radius:var(--r3); padding:2px 10px;
          font-size:var(--t-xs); color:var(--fg-3); white-space:nowrap; }
  .chip.vivo { color:var(--ok); border-color:#2f6b4c; }
  .chip.viejo { color:var(--warn); border-color:#6b532f; }
  .chip.local { color:var(--info); border-color:#2f4d6b; }
  /* Amenaza: el enemigo que no se busca solo. Rojo porque es lo único que, si se
     ignora, cuesta la partida. */
  .chip.peligro { color:var(--bad); border-color:var(--bad); background:var(--bad-bg); }
  /* Riesgo: el perfil histórico de la partida (muertes y participación). Ámbar
     mientras el corte solo avisa; rojo cuando las muertes ya no se enderezan solas. */
  .chip.riesgo { color:var(--warn); border-color:#6b532f; }
  .chip.riesgo.alto { color:var(--bad); border-color:var(--bad); background:var(--bad-bg); }
  .chip.oculto { display:none; }
  /* Una sola columna de 640: el texto mide ~450 px y la tarjeta se estiraba a 1 251 px
     dejando el precio a 1 089 del nombre (auditoría de UI). */
  main{
    width:100%; max-width:640px; margin-inline:auto; padding:var(--s5) var(--s4);
    display:grid; gap:var(--s4); align-content:start;
  }
  @media (max-width:640px){ main{ padding:var(--s4) var(--s3) } }
  .caja { background:var(--surface); border:1px solid var(--line);
          border-radius:var(--r2); padding:var(--s4); }
  h2 { font-size:var(--t-xs); font-weight:700; text-transform:uppercase;
       letter-spacing:.06em; color:var(--fg-3); margin:0 0 var(--s3); }
  /* La acción es la única dominante del panel. */
  .rec { display:flex; gap:var(--s3); align-items:center; min-height:64px; }
  .rec img { width:56px; height:56px; border-radius:10px; background:#0b0d11;
             flex:0 0 auto; }
  .rec .nombre { font-size:var(--t-xl); font-weight:800; line-height:1.1; }
  .rec .precio { color:var(--gold); font-variant-numeric:tabular-nums;
                 margin-top:var(--s1); }
  .faltan { color:var(--fg-2); font-variant-numeric:tabular-nums; }
  .razon { color:var(--fg-2); font-size:var(--t-sm); margin:var(--s3) 0 0;
           white-space:pre-line; }
  .venta { color:var(--bad); font-size:var(--t-sm); margin:var(--s2) 0 0; }
  .venta:empty, .razon:empty { display:none }
  /* Evidencia: si existe, va con su intervalo y su n. Un punto sin intervalo es una
     afirmación que no se puede sostener. */
  .evidencia { margin-top:var(--s3); padding-top:var(--s3);
               border-top:1px solid var(--line); font-size:var(--t-xs);
               color:var(--fg-3); display:none; }
  .evidencia.on { display:block }
  .evidencia b { color:var(--fg-2); font-weight:700 }
  .evidencia.contra { color:var(--warn) }
  .etiqueta { border:1px solid var(--line-2); border-radius:var(--r3);
              padding:0 6px; margin-right:var(--s2); font-size:var(--t-xs); }
  .etiqueta.medido { color:var(--ok); border-color:#2f6b4c }
  .etiqueta.preliminar { color:var(--warn); border-color:#6b532f }
  .etiqueta.debil { color:var(--fg-3) }
  .inv { display:flex; gap:var(--s1); flex-wrap:wrap; margin-top:var(--s4); }
  .inv .slot { width:36px; height:36px; border-radius:var(--r1);
               border:2px solid var(--line); background:#0b0d11; position:relative; }
  .inv .slot img { width:100%; height:100%; border-radius:5px; }
  /* Color de venta: rojo = sale primero, ámbar = candidato. */
  .inv .slot.vender-ahora { border-color:var(--bad); }
  .inv .slot.vender-luego { border-color:var(--warn); }
  .inv .slot em { position:absolute; bottom:-5px; right:0; font-size:10px;
                  font-style:normal; color:var(--bad); background:var(--surface);
                  padding:0 2px; border-radius:3px; }
  .vacio { color:var(--fg-3); min-height:56px; display:flex; align-items:center; }
  footer { border-top:1px solid var(--line); padding:var(--s3) var(--s4);
           color:var(--fg-3); font-size:var(--t-xs);
           display:flex; gap:var(--s4); flex-wrap:wrap; }
  img.roto { visibility:hidden }
  /* Sin coach no se finge que hay datos: se atenúa y se dice qué pasa. */
  body.sin-vivo .rec, body.sin-vivo #inv { opacity:.35 }
  body.sin-vivo .caja { border-style:dashed }
</style>
</head>
<body>
<header>
  <span id="conexion" class="chip">conectando…</span>
  <div class="hud">
    <span id="amenaza" class="chip oculto"></span>
    <span id="delta" class="chip oculto"></span>
    <span id="riesgo" class="chip oculto"></span>
  </div>
</header>

<main>
  <section class="caja">
    <h2>Compra ahora</h2>
    <div id="rec" class="rec"><span class="vacio">sin recomendación</span></div>
    <p id="razon" class="razon"></p>
    <p id="venta" class="venta"></p>
    <div id="evidencia" class="evidencia"></div>
    <div id="inv" class="inv"></div>
  </section>
</main>

<footer>
  <span id="fuente">fuente —</span>
  <span id="edad"></span>
  <span id="notas"></span>
</footer>

<script>
const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("es-MX");
// Repintado por nodo: si el HTML de una región no cambió, no se toca. Reconstruir todo
// cada segundo era lo que impedía cualquier transición (y hacía parpadear los iconos).
const _html = new Map();
function poner(el, html) {
  if (!el) return;
  if (_html.get(el.id) === html) return;
  _html.set(el.id, html);
  el.innerHTML = html;
}
const esc = (s) => String(s ?? "").replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;",
  "&": "&amp;", '"': "&quot;" }[c]));

function reloj(seg) {
  if (seg === null || seg === undefined) return "—";
  const m = Math.floor(seg / 60), s = Math.floor(seg % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// --- chip de riesgo (inicio) ---
/* Perfil histórico de la partida, no pronóstico.

   El motor manda `riesgo` con los dos cortes de las 3 538 partidas y solo cuando la
   partida lo sostiene (KDA leído, ≥5 min y datos de ahora); si no, manda null. Aquí
   se pinta una sola cosa, la que se puede mover: las muertes si ya se pasó de la meta
   o, si no, la participación. El contexto con su n va en el `title`, no en el texto:
   el panel se mira dos segundos entre peleas. */
function chipRiesgo(r) {
  if (!r || !(r.cruza_muertes || r.bajo_participacion)) return null;
  const muertes = Number(r.muertes);
  const texto = r.cruza_muertes
    ? `${muertes} muertes · meta ≤${r.muertes_meta}`
    : `${Number(r.participacion).toFixed(2)} k+a/min · meta ${Number(r.part_meta).toFixed(2)}`;
  return { texto: texto, clase: muertes > 8 ? "riesgo alto" : "riesgo",
           title: r.contexto || "" };
}
// --- chip de riesgo (fin) ---

function pintar(d) {
  const conexion = $("conexion");
  // La marca de «datos viejos» la decide el servidor (`rancio`, con su umbral); aquí no
  // se duplica el número para que no haya dos verdades distintas.
  const viejo = Boolean(d.rancio);
  const modo = d.modo || "";
  let texto = "en vivo", clase = "vivo";
  if (d.listo === false) {
    texto = modo === "CIEGO" ? "sin datos" : "esperando partida";
    clase = "";
  } else if (viejo) {
    texto = `datos de hace ${Math.round(d.edad_s || 0)} s`;
    clase = "viejo";
  } else if (modo === "SOLO_LOCAL" || d.fuente === "pantalla") {
    texto = "solo pantalla";
    clase = "local";
  }
  conexion.textContent = texto;
  conexion.className = "chip " + clase;
  conexion.title = d.mensaje || "";

  // Sin coach (o con datos viejos) el panel no enseña cifras vivas como si lo fueran.
  const vivo = d.listo !== false && !viejo;
  document.body.classList.toggle("sin-vivo", !vivo);

  // A quién no se busca solo. El motor ya lo calcula (`amenazas.peor`).
  const peor = (d.amenazas || {}).peor || {};
  const evitar = peor.evitar_solo ? String(peor.heroe || "") : "";
  const chipA = $("amenaza");
  chipA.textContent = evitar ? `⚠ no busques a ${evitar} solo` : "";
  chipA.className = "chip " + (evitar ? "peligro" : "oculto");

  const dp = (d.economia || {}).delta_pct;
  const chipD = $("delta");
  if (dp === null || dp === undefined) {
    chipD.className = "chip oculto";
  } else {
    chipD.textContent = `${dp >= 0 ? "+" : ""}${(dp * 100).toFixed(0)}% almas vs enemigos`;
    chipD.className = "chip " + (dp >= 0 ? "vivo" : "viejo");
  }

  // Riesgo: solo con datos vivos y solo cuando el corte dice algo. Es contexto
  // histórico —el motor ya devuelve null sin KDA, antes de 5 min o con datos viejos—,
  // así que aquí no se recalcula nada, solo se apaga cuando el panel no está en vivo.
  const chipR = $("riesgo");
  const r = vivo ? chipRiesgo(d.riesgo) : null;
  chipR.textContent = r ? r.texto : "";
  chipR.title = r ? r.title : "";
  chipR.className = "chip " + (r ? r.clase : "oculto");

  const rec = (d.recomendaciones || [])[0];
  if (rec) {
    poner($("rec"), `<img src="/icono/${esc(rec.id)}" alt=""
      onerror="this.classList.add('roto')">
      <div><div class="nombre">${esc(rec.nombre)}</div>
      <div class="precio">${rec.costo ? nf.format(rec.costo) + " oro" : ""}
      <span id="faltan" class="faltan"></span></div></div>`);
    $("razon").textContent = (rec.razones || [])[0] || "";
    const v = d.venta || {};
    $("venta").textContent = v.nombre
      ? `vende ${v.nombre} · entra ${v.para || ""}` : "";
    pintar_evidencia(rec, d);
  } else {
    // Sin partida, lo más útil que puede enseñar el panel es cómo fue la última.
    const nota = d.listo === false && d.ultima_nota ? String(d.ultima_nota) : "";
    poner($("rec"), `<span class="vacio">${
      nota ? "última partida" : vivo ? "sin recomendación"
        : (d.listo === false ? "esperando al coach"
        : `datos de hace ${Math.round(d.edad_s || 0)} s`)}</span>`);
    $("razon").textContent = nota || (d.listo === false ? (d.mensaje || "") : "");
    $("venta").textContent = "";
    $("evidencia").className = "evidencia";
  }

  // Sin «faltan» ni «te alcanza»: dependen de las almas del momento, que llegan del
  // broadcast con retraso (20-25 s) o de una lectura OCR que falla. Se retiraron el
  // 2026-11-18 junto con los del overlay y la tarjeta (Diego: solo certeza). El precio
  // de lista ya está en la recomendación; fingir precisión de oro costaba credibilidad.
  const faltan = $("faltan");
  if (faltan) faltan.textContent = "";

  // Inventario: solo cuando aporta una decisión (venta) o hay algo que comprobar.
  const inv = d.inventario || [];
  const hayVenta = inv.some((x) => x.vende === "ahora" || x.vende === "luego");
  const cajaInv = $("inv");
  if (hayVenta) {
    cajaInv.innerHTML = inv.map((x) => {
      const clase = x.vende === "ahora" ? "vender-ahora"
                  : x.vende === "luego" ? "vender-luego" : "";
      const marca = x.vende === "ahora" ? "<em>vende</em>" : "";
      return `<div class="slot ${clase}" title="${esc(x.nombre || "")}${
        x.vende_motivo ? " · " + esc(x.vende_motivo) : ""}">
        <img src="/icono/${esc(x.id)}" alt="" onerror="this.classList.add('roto')">${marca}</div>`;
    }).join("");
  } else {
    cajaInv.innerHTML = "";
  }

  $("fuente").textContent = `fuente ${d.fuente || "—"}`;
  $("edad").textContent = d.t === null || d.t === undefined ? ""
    : `reloj ${reloj(d.t)}` + (viejo ? ` · ${Math.round(d.edad_s || 0)} s de retraso` : "");
  // Dos notas como mucho y sin repetir: el pie es contexto, no un diario.
  const notas = (d.notas || []).slice(0, 2).join(" · ");
  $("notas").textContent = notas;
}

/* Evidencia: efecto, intervalo y n. Si el motor no trae las tres cosas, no se pinta
   nada. Mostrar un punto sin intervalo es lo que la especificación prohíbe. */
function pintar_evidencia(rec, d) {
  const caja = $("evidencia");
  const ev = rec.evidencia || d.evidencia || null;
  // Sin evidencia del ítem, el desempate medido ocupa el mismo renglón: dos avisos
  // distintos en dos líneas es ruido para una tarjeta que se mira 2 s.
  if (!ev && d.desempate && d.desempate.nombre) {
    caja.className = "evidencia on";
    caja.title = "El motor considera empatadas ambas compras; esta es la que el "
      + "laboratorio respalda fuera de muestra.";
    poner(caja, `el laboratorio prefiere <b>${esc(d.desempate.nombre)}</b>`
      + (Number.isFinite(d.desempate.efecto_pp)
          ? ` (${d.desempate.efecto_pp >= 0 ? "+" : ""}${d.desempate.efecto_pp.toFixed(1)} pp)`
          : ""));
    return;
  }
  if (!ev || ev.efecto_pp === undefined || ev.efecto_pp === null
      || !Array.isArray(ev.ic90) || ev.ic90.length !== 2 || !ev.n_partidas) {
    caja.className = "evidencia";
    return;
  }
  const etiqueta = ev.etiqueta || "debil";
  // El E-value se enseña al lado: dice cuánto tendría que pesar un confusor no medido
  // (la habilidad del jugador) para explicar el efecto entero. No es letra chica.
  const e = ev.evalue ? ` · E ${ev.evalue.toFixed(2)}` : "";
  // Veredicto explícito: un efecto negativo con intervalo entero bajo cero dice que
  // el laboratorio NO respalda esta compra; callarlo sería lo contrario de honesto.
  const juicio = ev.ic90[1] < 0 ? "⚠ no respalda · "
                : ev.ic90[0] > 0 ? "respalda · " : "";
  caja.className = "evidencia on" + (ev.ic90[1] < 0 ? " contra" : "");
  caja.title = "Asociación condicional, no causalidad: si existe un confusor de "
    + (ev.evalue ? `fuerza ${ev.evalue.toFixed(2)}` : "fuerza moderada")
    + " o más (por ejemplo, la habilidad del jugador, que no está en la base), "
    + "explica el efecto entero.";
  poner(caja, `${juicio}<span class="etiqueta ${esc(etiqueta)}">${esc(etiqueta)}</span>
    <b>${ev.efecto_pp >= 0 ? "+" : ""}${ev.efecto_pp.toFixed(1)} pp</b>
    <span>[${ev.ic90[0].toFixed(1)}, ${ev.ic90[1].toFixed(1)}]</span>
    · ${nf.format(ev.n_partidas)} partidas${e}
    ${ev.parche ? ` · parche ${esc(ev.parche)}` : ""}`);
}

// Si el estado no cambió, no se repinta: reconstruir el DOM cada segundo era lo que
// hacía imposible cualquier transición y provocaba el parpadeo de los iconos.
let _firma = null;
async function latir() {
  try {
    const r = await fetch("/api/estado", { cache: "no-store" });
    const d = await r.json();
    const firma = JSON.stringify(d);
    if (firma === _firma) return;
    _firma = firma;
    pintar(d);
  } catch (e) {
    $("conexion").textContent = "sin coach";
    $("conexion").className = "chip viejo";
    document.body.classList.add("sin-vivo");
  }
}
latir();
setInterval(latir, 1000);
</script>
</body>
</html>
"""
