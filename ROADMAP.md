# Hoja de ruta

Estado: **v1.0**. El ciclo diario está completo (listo → plan → panel/overlay → nota →
sesión), los datos por héroe y por parche existen, y el motor de ítems se cerró como
resultado negativo. Uso local de una persona. Este documento dice qué viene, en qué orden y
con qué criterio se considera terminado. Las fechas son objetivos, no promesas; lo que no se
mida no se marca como hecho.

## Dónde estamos

| Versión | Alcance | Estado |
|---|---|---|
| v0.1 | Lee la partida (broadcast y marcador), motor de compras, panel GTK | hecho |
| v0.2 | Panel responsive, SQLite, contra-composición, respaldo de modelos | hecho (2026-11-07) |
| v0.6 | Captura por caja, estado menú/partida/cierre, histórico de composiciones, ítems contra comp, camino por héroe, panel web | hecho (2026-11-15), pendiente la medición en partida real |
| v0.7 | Cuota de espectador persistida, sin URL no se especta, versión comprobable | hecho (2026-11-18) |
| v0.8 | Motor v2 con valor medido (AIPW + bootstrap por partida), corpus congelado con hash, cupo local de espectador, degradación a HUD, panel al contrato de siete zonas | hecho (2026-11-18) |
| v0.8.2 | G4: replicación fuera de muestra (Spearman 0.796, signo 90.5 %), desempate avisado en 19 de 21 ítems, pruebas de caos | hecho (2026-11-18) |
| v0.9 | Tarjeta 420×160 y overlay layer-shell con solo certeza; corpus filtrado a partidas completas; motor en modo CIEGO hasta reestimar; demos por SQL con 100 % de recall; estudio macro y diagnóstico personal; equipo documentado | hecho (2026-11-18) |
| v1.0 | Ciclo diario completo (`listo`, `plan`, `nota`, `sesion`), nota sin depender de la demo, 4 héroes y 20 parches de datos, motor de ítems cerrado con datos, Windows ejecutado bajo Wine, paquete probado, equipo portable, 528 pruebas | hecho (2026-11-18) |

## Lo que queda después de la v1.0

- **Demos**: el 429 del 2026-11-18 **no era de la API, era nuestro**. La respuesta dice
  `{"type":"IP","quota":{"limit":200,"period":3600},"requests":202,"remaining":0}`: el
  techo documentado de `/demo/query` es 200 peticiones por hora **por IP**, y cada partida
  consume 2 trabajos más un sondeo cada 2-5 s por trabajo. Con eso, la hora se agota en
  ~20 minutos y quedan ~7 partidas/hora, no 800.
  Arreglado: `CupoHorario` (170/h propias, cuenta también los sondeos) y sondeo cada
  5-15 s. Aun así son ~12 partidas/hora. Las 800 no salen de preguntar por la API: salen
  de bajar el `.dem` (`demo_url` viene en `/v1/matches/demo/schema`) y parsearlo aquí, o
  de una API key (400/h, solo duplica).
- **Windows nativo**: overlay y captura corren bajo Wine (10 comprobaciones, GDI 27,7 ms).
  Falta DXGI real, compositor, instalador y una máquina donde medirlo.
- **La subida de rango**: el producto está listo; falta que se juegue una sesión y que
  `sesion` diga qué regla se fue.

## Lo que queda de la v0.9 (prioridad)

- **Motor de ítems · cerrado como resultado negativo (2026-11-18).** Se recorrió el camino
  completo: la contaminación por modo, la riqueza relativa, el contrafactual del mismo tramo
  de precio y, al final, la serie de 20 parches con 63 680 compras. **Ningún ítem tiene un
  efecto demostrado ni réplica**; el límite es la muestra (~200 partidas de Abrams por
  parche), no el meta. Harían falta dos órdenes de magnitud. El panel no enseña evidencia por
  ítem y no debe: su valor está en el camino, las reglas y la nota. Informe:
  `informes/lab/PARCHES-MODELO-2026-11-18.md`.
- **Ingesta continua de demos.** No backfill de 5 000 (caducan): crawl de partidas recién
  terminadas, con `CurrencyChangedEvent` para el oro real. `docs/DATOS-DEL-JUEGO.md`.
- **Windows**: el código de overlay y captura **se ejecuta bajo Wine** (`herramientas/
  probar_windows_wine.sh`, 10 comprobaciones) y la captura por GDI mide **27,7 ms** por
  cuadro contra 415–514 ms de KWin. Falta DXGI real, compositor y el instalador; sin una
  máquina Windows no se puede cerrar.
- **Overlay en partida real**: probado con un proceso falso, no con Deadlock abierto.

- **Aviso de riesgo en vivo.** Las reglas de muerte y participación están validadas en
  3 538 partidas (≤6 muertes: 76.9 % vs 36.2 %; ≥0.40 participación: 70.9 % vs 12.8 %). El
  panel ya recibe K/D/A del broadcast: puede enseñar el umbral y avisar cuando se cruza, con
  el dato histórico como contexto, no como predicción. Sin inventar: si no hay KDA, no hay aviso.

## Lo que queda de la v0.8

- **G4 · hecho, y no autorizó reordenar.** La replicación fuera de muestra sostiene el
  signo en 19 de 21 ítems (Spearman 0.796), así que se habilitó un **desempate avisado**;
  el valor de política con DR no distingue (ESS 640 de 14 397). Para reordenar de verdad
  hace falta ESS ≥ 25 %, más acciones con soporte y MMR. Ver `informes/lab/G4-POLITICA.md`.
- **Más corpus.** 21 ítems medidos de 170: el shortlist por franja recorta. Con más
  partidas (otros parches, otros días) entran más ítems y los intervalos se estrechan.
- **MMR.** `partidas_api.badge` es nulo en el 88 %; sin MMR no hay instrumento para el
  confusor de habilidad y el E-value del mejor hallazgo es 1.36. Es la prioridad 1 de
  datos, no de código.
- **Migrar `/v1/sql` a DuckDB.** Está deprecado por la API y el código que lo usa tiene
  cuenta atrás.

## Lo que queda de la v0.6

- **Medición en partida real**: `herramientas/medir_impacto.py` mide GPU, CPU y RAM sin
  overlays; falta correrlo con el juego abierto y ver el fin de partida en el log.
- **Economía por héroe**: la apertura y el camino ya salen de los datos de cada héroe, pero
  el ranking de ítems y los contras siguen siendo de Abrams. Para generalizarlos hace falta
  bajar timelines de otros héroes (`archivo_abrams.py --heroe <id> --con-items`).
- **Plantilla completa con muestra**: con 151 653 partidas la comp más repetida sale 18
  veces; a 300–400k empezaría a repetir en serio.

## Qué falta para que sea un producto

Cinco frentes, en orden de impacto. Cada uno tiene su medida de salida.

### F1 · Latencia (lo que más se nota)

El broadcast de Valve llega 20–25 s tarde. Eso no se puede "optimizar": es el TV del juego.
Lo que sí se puede es dejar de depender de él para lo que cambia cada segundo.

| Paso | Qué | Salida medible |
|---|---|---|
| F1.1 | ~~Medir la cadena completa y mostrar cada latencia por separado~~ | **hecho**: el pie muestra captura, lectura y cuánto va el TV por detrás |
| F1.2 | ~~Reloj y oro del HUD por visión a 2–5 Hz~~ | **hecho**: lectura en 127 ms, 7.9 lecturas/s; falta validar con captura real |
| F1.3 | Inventario propio por plantillas (fila inferior del HUD) | 12 slots reconocidos con ≥ 95 % en capturas reales |
| F1.4 | Proyección entre actualizaciones (almas extrapoladas por ritmo) | el panel marca "proyectado" y corrige al llegar el dato |
| F1.5 | ~~Captura compartida a un solo proceso~~ | **hecho**: `coach/fuentes/captura.py`, una captura por ciclo |

Meta: **tiempo y oro a menos de 1 s** de lo que ve el jugador; el resto (enemigos, KDA) sigue
en los 20–25 s del broadcast, pero etiquetado con su edad real.

### F2 · Visión (lo que hoy es frágil)

| Paso | Qué | Salida medible |
|---|---|---|
| F2.1 | Localizar el bloque de oro por color (teal) en vez de caja fija | funciona a 1080p, 1440p y con HUD desplazado |
| F2.2 | Marcador (12 almas) con tesseract preprocesado, 1 llamada | 12/12 números, ≤ 200 ms (ya medido: 130 ms) |
| F2.3 | Ítems del enemigo por template matching de la fila del marcador | top-6 de cada enemigo, ≥ 90 % |
| F2.4 | FPS desde fuera del juego, sin overlay | fuente fiable o se descarta y se dice |
| F2.5 | Marco de referencia por resolución y por parche | detectar cambio de HUD en vez de fallar en silencio |

### F3 · Producto distribuible

| Paso | Qué | Salida medible |
|---|---|---|
| F3.1 | Instalador de una línea para Arch/CachyOS y Debian/Ubuntu | instalación limpia en una VM sin pasos manuales |
| F3.2 | Configuración guiada (detecta monitor y resolución) | `abrams-coach configurar` deja todo listo |
| F3.3 | Documentación de usuario separada de la de ingeniería | alguien sin contexto puede usarla leyendo un archivo |
| F3.4 | Licencia y política de datos | cero telemetría, cero cuentas, cero subida de capturas |
| F3.5 | Empaquetado (AppImage o tarball + PKGBUILD) y releases con notas | descarga y ejecuta sin compilar |

### F4 · Más héroes

Hoy todo el conocimiento está atado a Abrams: apertura, hitos de almas y matchups. El motor
ya es genérico; lo que falta es el dato por héroe.

| Paso | Qué | Salida medible |
|---|---|---|
| F4.1 | ~~Separar `data/heroes/abrams.json` del código~~ | **hecho**: el motor lee el héroe del estado y cae a Abrams si no hay datos |
| F4.2 | Segunda base: 3 héroes con datos completos | apertura, hitos y counters por héroe |
| F4.3 | Selector de héroe en la app (auto por cuenta, manual si falla) | detecta el héroe del broadcast |
| F4.4 | Cobertura de 10 héroes | ≥ 1,000 partidas reales por héroe |

### F5 · Inteligencia sin teclado

El chat se descartó: en partida no se puede escribir. La IA se usa donde no estorba.

| Paso | Qué | Salida medible |
|---|---|---|
| F5.1 | Informe de partida automático al terminar (SQLite + modelo) | un resumen por partida, con qué se compró y qué se recomendó |
| F5.2 | Explicación precalculada de alternativas | cada recomendación trae por qué no las otras dos |
| F5.3 | Avisos proactivos en el panel (una línea, sin interacción) | cuando cambia la amenaza o se cruza un hito |

## Calendario propuesto

| Cuándo | Qué se cierra |
|---|---|
| Sesión actual (2026-11-07) | F1.1, F2.1, F3.3, F5.2 y limpieza de producto |
| Próximas 2 sesiones | F1.2–F1.5 (latencia real), F2.2 |
| Después | F2.3–F2.5, F3.1–F3.2 |
| Más adelante | F4.1–F4.4, F3.4–F3.5 |

## Lo que NO se va a hacer

- Overlays dentro del juego, lectura de memoria, inyección o macros. Riesgo de ban y no
  aporta: la app vive en el segundo monitor.
- Chat dentro de la partida. Se descartó el 2026-11-07: nadie alt-tab-ea a media pelea.
- Gráficos decorativos, animaciones de adorno, contadores "de vanidad".
- Funciones que no se puedan medir. Si no hay forma de demostrar que sirve, no entra.
- Dependencias pesadas (Electron, Docker, servicios en la nube) para una app que debe caber
  en 150 MB de RAM junto a un juego que ya va justo.
