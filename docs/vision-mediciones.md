# Visión bajo demanda: lo que se midió con la API real

Medido el **2026-11-09** entre 12:55 y 13:05 (America/Monterrey) contra
`api.commandcode.ai` (`deepseek/deepseek-v4.1-flash`) y `router.huggingface.co`
(`deepseek-ai/DeepSeek-V4.1-Flash`), con cuadros de una ranked en curso.

## Latencia y peso

| Qué se manda | Peso | commandcode | huggingface |
|---|---|---|---|
| Texto sin imagen | — | 3.0 s ✔ | — |
| Imagen de 320×180 (prueba de color) | 0.6 kB | 5.1 s ✔ | 1.9 s ✔ |
| Escritorio completo 4480×1440 → 960 px q70 | 35 kB | **timeout 25 s** | 16.5 s ✔ (2 710 tok) |
| Escritorio completo → 1280 px q60 | 47 kB | **timeout** | **timeout** |
| Recorte del juego → 1024 px q78 | 85 kB | — | **timeout 40 s** |
| Recorte del juego → 768 px q72 | 46 kB | — | **timeout 40 s** |
| Recorte del juego → 640 px q70 | 33 kB | — | **23.4 s ✔ (3 603 tok)** |

## Qué significa para el diseño

1. **El umbral práctico son ~40 kB de JPEG.** Por encima, la petición no vuelve: da igual
   subir el timeout, se cae igual. El formato que sirve es recorte del monitor del juego,
   640 px de lado mayor, calidad 70.
2. **Una lectura tarda ~23 s, no 3.** El objetivo de "latencia < 3 s" del relevo no es
   alcanzable con este proveedor y este tamaño; se cambia el criterio: el panel no espera
   nunca a la visión, pinta lo último con su edad.
3. **1 cuadro cada 5 s no se puede cumplir esperando.** Por eso la cola mantiene **una
   sola petición en vuelo** y encola lo demás, con prioridad para la tienda y el marcador.
4. **El costo por cuadro es ~3 600 tokens.** Con el tope de 300 cuadros por partida son
   ~1.08 M tokens por partida; el presupuesto de 5 B aguanta ~4 600 partidas.

## Respuesta real del modelo (640 px, tienda cerrada)

```json
{"fase": "en_partida", "en_partida": true, "espectando": false,
 "reloj_s": null, "oro": 1585, "almas": null, "tienda_abierta": false,
 "marcador_abierto": false, "items": [], "slots": {}, "enemigos": [],
 "huevo": null, "confianza": 0.3, "notas": "..."}
```

Leyó el oro y la fase; dejó el reloj en `null` y bajó la confianza a 0.3. Eso es lo
correcto según las reglas: no inventar. La lectura fina (reloj, almas, inventario) pide
recortes de zona —HUD, tienda— en vez del cuadro entero del juego.

## Siguiente medición pendiente

- Recortes por zona (HUD arriba, tienda centrada) a 640 px: ¿baja la latencia y sube la
  confianza?
- Cuadro con la tienda abierta: ¿devuelve 6–12 ids válidos contra `data/catalogo.json`?
- Coste real de tokens por partida con la cadencia final.

## Primera lectura con la partida en curso (integrada al coach)

Con la cola conectada al bucle, `--vision-cada 20` y el recorte del monitor del juego
(2560×1440 → 640 px), sobre una ranked en curso:

| Medición | Valor |
|---|---|
| Latencia por cuadro (huggingface primero) | **23.3 s** |
| Tokens por cuadro | **3 612** |
| Proveedor que contestó | huggingface (`deepseek-ai/DeepSeek-V4.1-Flash`) |
| Fallos de la cola | 0 |
| Fase leída | `en_partida` ✔ |
| Reloj | `null` — el HUD a 640 px no se lee |
| Oro | 4 348 (confianza 0.40, sin verificar contra el HUD) |

Y con commandcode primero (como estaba antes), el mismo cuadro:

| | |
|---|---|
| Latencia | **56.1 s** (30 s de tiempo de espera agotado + ~23 s de huggingface) |
| Tokens | 3 612 |
| Fallos | 0 (el respaldo lo salvó) |

Por eso `cadena_vision()` pone **huggingface primero** y commandcode como respaldo: el
orden no es estético, son 33 s de diferencia por cuadro.

## Lo que la visión todavía no lee (y por qué)

A 640 px el cuadro entero del juego es demasiado pequeño para el reloj y para el texto de
la tienda. El reloj ya lo da el OCR local del HUD (exacto, 200 ms) y el inventario necesita
**recortes de zona**: la tira del reloj, el bloque de oro y, con B abierta, el panel de la
tienda. Eso es la siguiente medición: cuánto baja la latencia y cuánto sube la confianza
al mandar 6–10 kB de la zona en vez de 33 kB del cuadro completo.

## Tira del HUD: el formato que sí sirve (medido en partida, 2026-11-09)

Se recortan dos zonas a tamaño nativo y se apilan (320 px de ancho, 10 kB): arriba el
reloj y las almas de equipo; abajo el oro («$N SOULS») y la rejilla de ítems.

| Lectura | Peso | Latencia | Tokens | Valores |
|---|---|---|---|---|
| Solo el reloj | 0.9 kB | 1.3 s | 314 | `reloj_s: 56` ✔ |
| Solo el bloque de oro | 1.7 kB | 3.4 s | 601 | región mal calibrada en `regiones.json` |
| Tira completa | 10.5 kB | 24 s | 650 | reloj 180 ✔ oro 555 ✔ ítems 1 ✔ almas 10 000 ✔ |
| Tira completa (3 intentos) | 10.5 kB | 28–40 s | 926–1 041 | 1 de 3 aciertos; 2 sin respuesta |

**Los cuatro números salieron correctos** cuando hubo respuesta: se verificaron contra la
imagen (3:00, $555, un ítem, 10k de equipo) y contra el reloj del HUD del coach (180 s
contra 211 s, con 31 s de diferencia real entre las dos capturas).

Lo que **no** es fiable todavía es la latencia: entre 1.3 s y 40 s, con fallos por tiempo
de espera. Por eso la visión va en cola y el panel pinta lo último con su edad; nunca se
espera a la visión para decidir. `--vision-cada 25` es el ritmo que deja respirar a la API.

## Trampa encontrada: `config/regiones.json` está descalibrado

La región `almas` (`[0.36, 0.93, 0.12, 0.045]`) apunta a un trozo de HUD donde solo hay
un «2» suelto: el modelo lo leyó como `{"almas": 2}`. Las zonas buenas para el HUD actual
son:

| Zona | Fracciones del área de juego |
|---|---|
| Reloj + almas de equipo | `[0.44, 0.00, 0.14, 0.08]` |
| Oro + rejilla de ítems | `[0.00, 0.80, 0.16, 0.18]` |

Están en `coach/agente/vision_zonas.py`; `regiones.json` hay que recalibrarlo aparte.
