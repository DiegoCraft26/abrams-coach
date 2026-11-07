# Abrams Coach

Panel de decisiones para Deadlock. Lee tu partida desde la pantalla y desde el broadcast
público, y te dice qué comprar, cuándo vender y si toca farmear o pelear. Vive en el
segundo monitor: no dibuja nada encima del juego.

Estado actual: **v0.2**, solo Abrams, español.

![Panel a 1280x720](capturas/ui-1280x720.png)

## Instalación

```bash
cd .
./instalar.sh                # comprueba dependencias y deja el comando en PATH
```

Dependencias: Python 3.11+, GTK4, `tesseract`, `spectacle` (viene con KDE), Pillow y NumPy.
El instalador dice cuál falta y no toca nada más.

## Uso

```bash
abrams-coach demo            # panel con datos de ejemplo, sin abrir el juego
abrams-coach jugar           # prepara la máquina, abre el coach y el panel
abrams-coach estado          # qué corre, cuánta RAM usa, qué leyó
abrams-coach archivar        # guarda la partida en la base local
abrams-coach informe         # resumen de la última partida
```

Sin instalador:

```bash
./arrancar.sh simulado && python3 panel_nativo.py
./herramientas/partida.sh prep
```

## Qué te dice

| Sección | Qué contiene |
|---|---|
| Cabecera | reloj, oro sin gastar, patrimonio, ventaja de almas y estado táctico |
| Compra | un solo ítem, con dos razones medidas y lo que falta si no te alcanza |
| Inventario | tus 12 slots con el rendimiento de cada ítem frente a lo esperado |
| Enemigos | almas y KDA de los cinco rivales |
| Plan | las dos compras que suelen seguir, del grafo de 1.9 millones de partidas |
| Contra su composición | ítems que la amenaza enemiga justifica, con su fuente |
| Ventas | cuándo vender rinde más que seguir ahorrando |
| Pie | latencia real de cada eslabón |

Atajos: `1` compra, `2` enemigos, `3` compras, `?` ayuda, `Esc` cerrar. La ventana recuerda
tamaño y posición.

## Cómo funciona

1. **Captura** la pantalla con `spectacle`, la herramienta del sistema. Un hilo captura y
   todos los lectores usan el último cuadro.
2. **Lee** el reloj y el oro del HUD con OCR, y el marcador con plantillas del propio
   juego. Nada de leer memoria del juego.
3. **Recibe** el broadcast público por `deadlock-api`: héroes, KDA y almas de los rivales.
4. **Decide** ordenando los ítems por *lift residual*: cuánto rinde un ítem por encima de
   lo que predice su minuto típico de compra.
5. **Publica** el estado en `http://127.0.0.1:8090`; el panel lo consume.

Detalle técnico: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).
Lo que la app hace y no hace con el juego: [`POLITICA.md`](POLITICA.md).
Qué viene: [`ROADMAP.md`](ROADMAP.md).

## Lo que se midió

| Qué | Número | Cómo |
|---|---|---|
| Captura de pantalla | 415–514 ms por cuadro (4480×1440) | `herramientas/medir_latencia.py` |
| Lectura del HUD | 147 ms reloj, 122 ms oro | el mismo comando |
| Latencia del broadcast | 20–25 s (del TV de Valve, no nuestra) | reloj del HUD contra reloj del broadcast |
| Motor de decisión | 4.5 ms medio, 8.6 ms máximo | 2,156 estados de 200 partidas reales |
| Panel | 127 MB de RAM, 0.2 % de CPU | `ps` y `/proc/<pid>/stat` |
| Pruebas | 25 suites, 6/6 invariantes | `pytest -q` |

## Límites conocidos

- El broadcast llega 20–25 s tarde. Se muestra con su edad; no se disimula.
- El marcador solo se lee con Tab abierto.
- Los ítems del rival se ven cuando el broadcast los manda; el build completo no.
- El contador de FPS no tiene fuente fiable sin overlays. Ver
  [`informes/investigacion-fps.md`](informes/investigacion-fps.md).
- La calibración del HUD depende de la resolución y del parche.

## Desarrollo

```bash
python3 -m py_compile run.py panel_nativo.py coach/*.py coach/*/*.py
PYTHONPATH=$HOME/.dsh/bin/pylib python3 -m pytest -q
python3 tests/test_invariantes.py
python3 herramientas/capturar_ui.py          # 4 capturas + gate de pintado
python3 herramientas/evaluar_motor.py --partidas 200
```

Puertas de calidad: [`CALIDAD.md`](CALIDAD.md). Relevo: [`RELEVO.md`](RELEVO.md).
