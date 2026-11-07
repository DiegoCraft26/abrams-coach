# Hoja de ruta

Estado: **v0.2**, solo Abrams, uso local de una persona. Este documento dice qué viene, en
qué orden y con qué criterio se considera terminado. Las fechas son objetivos, no promesas;
lo que no se mida no se marca como hecho.

## Dónde estamos

| Versión | Alcance | Estado |
|---|---|---|
| v0.1 | Lee la partida (broadcast y marcador), motor de compras, panel GTK | hecho |
| v0.2 | Panel responsive, SQLite, contra-composición, respaldo de modelos | hecho (2026-11-07) |

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
