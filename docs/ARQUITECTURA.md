# Arquitectura

Cómo está armado el coach y por qué. Si vas a tocar código, esto primero.

## Flujo de datos

```
spectacle (415-514 ms)          deadlock-api SSE (20-25 s)
        |                                |
  captura compartida                en_vivo.Escucha
        |                                |
   hud_rapido (OCR)                estado_del_broadcast
        \                               /
          \___ run.py: bucle_vivo _____/
                        |
                  motor.recomendar
                        |
              servidor EST (bus)  --->  /api/estado  --->  panel GTK4
                                                 \--->  panel web
```

Una sola captura por ciclo: `coach/fuentes/captura.py` mantiene un hilo con el último
cuadro. Los lectores (HUD, marcador, partida) miran ese cuadro en vez de capturar cada uno.

## Módulos

| Módulo | Responsabilidad | No debe |
|---|---|---|
| `run.py` | cablear fuentes, motor, servidor y bucles | tener lógica de decisión |
| `coach/motor.py` | puntuar ítems y elegir | saber de dónde vienen los datos |
| `coach/decision/` | patrones, situacionales y explicaciones | leer archivos |
| `coach/fuentes/` | obtener estado (API, HUD, captura, demo) | decidir |
| `coach/estado.py` | normalizar un dict en `Estado` | tocar red o disco |
| `coach/servidor.py` | publicar `/api/estado` y SSE | calcular recomendaciones |
| `coach/persistencia/` | SQLite, migraciones y consultas | formatear texto para el panel |
| `coach/ui/` | pintar y recordar preferencias | conocer las fuentes |
| `coach/agente/` | informe de partida con modelo | ejecutarse durante la partida |

## Decisiones que se tomaron y por qué

**Un solo hilo de captura.** Capturar cuesta 415–514 ms. Con un lector por módulo, un ciclo
de tres lectores costaba más de un segundo. Con un cuadro compartido, el coste es el de una
captura y los lectores se reparten el tiempo de CPU.

**El motor no conoce las fuentes.** Recibe un `Estado` y devuelve una decisión. Eso permitió
evaluarlo contra 626 partidas reales sin abrir el juego (`herramientas/evaluar_motor.py`).

**Señales de reloj en bloques de 10 s.** Dos consultas separadas por 4 s caían a lados
distintos de la rampa de apertura y el ítem recomendado cambiaba. Con bloques, "casi el
mismo momento" da la misma respuesta. Hay un invariante que lo vigila.

**Los ítems situacionales no entran al ranking.** Sus datos de residual son negativos
porque los compra quien va perdiendo. Se muestran aparte, con su fuente y el motivo, en vez
de falsear la recomendación principal.

**Nada de chat.** Se descartó el 2026-11-07: durante una partida no se puede escribir. La
IA se usa antes y después (informe de partida), no en el momento.

**El panel consume HTTP, no el estado interno.** Así el panel web y el nativo ven lo mismo,
y el servidor puede correr sin ventana.

## Configuración

`config/coach.yaml`. Se carga con `coach/config.py`, que:

- corrige valores fuera de rango contra una tabla de límites,
- anota cada corrección en `cfg.avisos`,
- no lanza nunca: un YAML roto cae a los valores por defecto.

Banderas (`flags`): `patrones_nuevos`, `informe_partida`, `hud_ocr`, `archivado_auto`,
`interfaz_responsive`. Todo lo nuevo se puede apagar sin revertir código.

## HUD por visión

`coach/fuentes/hud_rapido.py`. Dos lecturas por cuadro:

1. **Reloj**: recorte fijo, escala ×6, autocontraste e inversión, tesseract `--psm 7`.
   147 ms.
2. **Oro**: primero se busca el bloque por color dentro de una banda
   (`fuentes.hud.color_oro`); si no hay color configurado o no aparece, se usa la caja fija.
   122 ms.

Las cajas están en `coach/fuentes/hud_rapido.py` (`CAJAS_DEFECTO`) y se pueden sobrescribir
en `config/coach.yaml`. Se escalan según el tamaño real del cuadro.

Para recalibrar con una captura nueva:

```bash
python3 - <<'PY'
from PIL import Image
im = Image.open("captura.png").convert("RGB")
# imprime el color dominante de la zona donde está el número de oro
from collections import Counter
zona = im.crop((1950, 1080, 2450, 1440))
print(Counter(zona.getdata()).most_common(5))
PY
```

## Persistencia

`datos/coach.db`, SQLite con WAL y migraciones idempotentes. Tablas: `partidas`,
`muestras`, `compras`, `recomendaciones`, `resultados`, `videos`, `agente_log`,
`migraciones`.

`herramientas/archivar.py` importa `salida/*.jsonl` y los videos. Es idempotente: correrlo
dos veces no duplica filas (lo comprueba `tests/test_persistencia.py`).

## Pruebas

| Suite | Qué protege |
|---|---|
| `test_motor` | decisiones coherentes y latencia < 20 ms |
| `test_invariantes` | 6 invariantes del motor sobre 50 estados |
| `test_robustez` | basura de entrada sin excepciones |
| `test_lectura`, `test_deteccion`, `test_autocalibrado` | lectura del marcador e iconos |
| `test_en_vivo`, `test_vivo_*` | mapeo del broadcast y datos congelados |
| `test_servidor` | `/api/estado` con edad y rancio |
| `test_persistencia` | archivado idempotente |
| `test_backend` | dominio, bus y config |
| `test_fuentes` | precedencia de fuentes y validación del HUD |
| `test_agente` | credenciales, presupuesto y lista blanca |
| `test_ui` | la ventana se construye y se pinta en 4 tamaños |
