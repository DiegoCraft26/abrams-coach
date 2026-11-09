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
