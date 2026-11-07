# Mediciones

Todos los números de este documento se midieron en la máquina de desarrollo (Ryzen 7 5700G,
RX 7600, 15 GB de RAM, KDE Wayland) el **2026-11-07**, salvo donde se indique otra fecha.
Cada fila dice con qué comando se reproduce.

## Latencia

| Eslabón | Medida | Reproducir |
|---|---|---|
| Captura de pantalla (4480×1440, `spectacle -f`) | 415–514 ms | `python3 herramientas/medir_latencia.py` |
| Captura de un solo monitor (`spectacle -m`, 2560×1440) | 314 ms | el mismo, con `-m` |
| Lectura del HUD (reloj y oro en paralelo) | 127 ms, 7.9 lecturas/s | el mismo |
| Broadcast de Valve (TV del juego) | 20–25 s | comparación reloj HUD contra reloj del broadcast |
| Ciclo completo del panel (estado → píxeles) | < 1 s | `abrams-coach estado` |

Antes de este trabajo, el HUD se leía a 269 ms por ciclo (reloj y oro en serie) y la captura
se repetía por cada lector. El reloj y el oro ahora van con ~0.5 s de retraso; el resto del
estado sigue en los 20–25 s del broadcast y así se muestra.

## Motor

Conjunto: 200 partidas reales de Abrams (`data/replay_cache.json`), 2,156 estados, compras
reales después del minuto 10. Reproducir:
`python3 herramientas/evaluar_motor.py --partidas 200 --max-estados 3000`.

| Configuración | Residual top-1 | Diversidad | Estabilidad | Razones |
|---|---|---|---|---|
| base (reglas nuevas apagadas) | +0.0558 pp | 15 | 72.4 % | 6.11 |
| + castigo de presupuesto | +0.0554 pp | 17 | 67.6 % | 6.01 |
| + castigo de comeback | +0.0558 pp | 15 | 72.4 % | 6.11 |
| + balance de slots | +0.0556 pp | 14 | 72.5 % | 6.05 |
| + contexto de composición | +0.0557 pp | 16 | 73.9 % | 6.26 |
| **todo encendido** | +0.0552 pp | **19** | 70.7 % | 6.18 |

Latencia del motor: 4.5 ms de media y 8.6 ms de máxima sobre esos 2,156 estados.

El castigo de comeback no se puede medir con el replay (no trae almas enemigas), así que se
midió con escenarios sintéticos (`herramientas/escenarios_motor.py`): yendo 25 % atrás, la
recomendación pasó de un ítem de 6,400 a uno de 1,600.

## Interfaz

| Métrica | Antes (v0.1) | Ahora (v0.2) | Reproducir |
|---|---|---|---|
| RAM del panel | 125.7 MB | 127.5 MB | `ps` a los 18 s |
| CPU del panel | 1.5 % | 0.2 % | `/proc/<pid>/stat` durante 18 s |
| Tamaños probados | 960×1080 fijo | 960×1080, 1280×720, 1920×1080, 800×600 | `herramientas/capturar_ui.py` |
| Captura de la ventana | — | PNG por render, sin depender del compositor | el mismo |

## Lectura de pantalla

| Qué | Resultado | Fecha y fuente |
|---|---|---|
| 12 almas del marcador (tesseract preprocesado, 1 llamada) | 12/12 números, 130 ms | 2026-11-07, `experimentos/hud/informe-B-tecnicas-hud.md` |
| Iconos de ítem con el icono al 100 % de la celda | 90–100 % | `tests/test_deteccion.py` |
| Iconos al 70 % de la celda | 85 % | el mismo |
| Reloj y oro del HUD sintético | correctos en 4 casos | `tests/test_latencia.py` |

## Base de datos

`datos/coach.db` al cierre: 2 partidas, 1,936 muestras, 5,289 recomendaciones, 5 videos.
Archivar dos veces seguidas inserta 0 filas nuevas (`tests/test_persistencia.py`).

## Lo que NO está medido

- FPS del juego con la app corriendo: no hubo partida abierta.
- Escalado 125 %/150 % de la interfaz.
- Latencia real del broadcast en una partida nueva (la de 20–25 s viene de la sesión
  anterior y de la documentación de la API).
- Acierto del oro por visión sobre capturas reales del HUD.
