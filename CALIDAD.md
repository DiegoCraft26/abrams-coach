# Puerta de calidad

Nada se da por bueno "porque se ve bien". Cada entrega pasa por estas comprobaciones.

## Automáticas (`verificar_ui.py`)

Se ejecuta contra el panel real con Playwright y **falla** si algo se rompe:

| Comprobación | Criterio |
|---|---|
| Desbordamiento horizontal y vertical | 0 px en los tres tamaños |
| Imágenes rotas | 0 |
| Slots de inventario | exactamente 12 |
| Icono principal en 960×1080 | ≥ 180 px |
| Título no vacío | obligatorio |
| Indicador de vivo con estado | `on` u `off`, nunca neutro |
| Contraste de texto | ≥ 4.5:1 (WCAG AA) |
| Errores de consola | 0 |

Tamaños probados: **960×1080** (mitad derecha del monitor), **1280×720**, **600×900**.

```bash
./arrancar.sh simulado
PYTHONPATH=~/.dsh/bin/pylib python3 verificar_ui.py
```

## Automáticas (motor)

| Comprobación | Criterio |
|---|---|
| `tests/test_motor.py` | decisiones coherentes, nada por encima de tus almas, latencia < 20 ms |
| `tests/test_robustez.py` | 308 entradas basura sin excepciones |
| `tests/test_deteccion.py` | ≥ 85% de acierto con icono al 70% de la celda |
| `evaluador.py` | AUC y ventaja medidos contra partidas reales |

## Coherencia de estados (manual, cada cambio de UI)

- **Conectando**: se ve el esqueleto, nada de ítems viejos.
- **Sin partida**: mensaje claro, indicador apagado, sin datos falsos.
- **En vivo**: hora, almas y ventaja actualizadas; recomendación estable.
- **Lectura dudosa**: título explícito, confianza baja, se mantiene la última buena.
- **Fase inicial**: no inventa compras; dice que aún no toca.

Regla de oro: **el panel nunca muestra un dato que no pueda respaldar**. Si no lee, lo dice.

## Señales de alarma

Si aparece cualquiera de estas, algo se degradó y hay que parar:

1. La recomendación cambia más de una vez cada 10 segundos.
2. El panel dice "estable" pero el título cambia entre capturas.
3. Aparecen ítems que no puedes pagar.
4. El indicador dice "en vivo" con el juego cerrado.
5. El contraste de algún texto baja de 4.5:1.
