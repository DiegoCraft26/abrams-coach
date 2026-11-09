# Puerta de calidad

Nada se da por bueno "porque se ve bien". Cada entrega pasa por estas comprobaciones.
Actualizado el 2026-11-07 con las puertas de la sesión de 9 h.

## Suite de pruebas (`pytest -q`)

```bash
python3 -m pytest -q                                        # 29 pruebas
python3 tests/test_invariantes.py                            # 6/6 invariantes
```

| Suite | Qué garantiza |
|---|---|
| `test_motor.py` | decisiones coherentes, nada por encima de tus almas, latencia < 20 ms |
| `test_camino.py` | camino apertura→core→spike, estados COMPRAR/AHORRAR/VENDER y componente del objetivo |
| `test_robustez.py` | 308 entradas basura sin excepciones |
| `test_invariantes.py` | 6 invariantes del motor sobre 50 estados sintéticos + informe de violaciones |
| `test_lectura.py` | lectura de marcador contra tu verdad terreno (se salta sin capturas) |
| `test_deteccion.py` / `test_autocalibrado.py` | reconocimiento de iconos ≥ 90 % con semilla fija |
| `test_en_vivo.py` / `test_vivo_*.py` | mapeo del broadcast, congelado y no publicar datos viejos |
| `test_servidor.py` | `/api/estado` con `edad_s` y `rancio` |
| `test_persistencia.py` | SQLite idempotente: archivar dos veces no duplica |
| `test_backend.py` | dominio, bus y config (66 comprobaciones) |
| `test_fuentes.py` | compuesto de fuentes, validación HUD, estado honesto |
| `test_agente.py` | credenciales, presupuesto, lista blanca de endpoints, respaldo |
| `test_ui.py` | **la ventana se construye y se pinta en los 4 tamaños** |

`test_ui.py` existe porque el 2026-11-07 un `NameError` al construir el drawer del copiloto
dejó el panel sin abrir y las capturas viejas no lo detectaron.

## Motor: medición, no impresión

```bash
python3 herramientas/evaluar_motor.py --partidas 200   # A/B sobre 2,156 estados reales
python3 herramientas/escenarios_motor.py               # comeback y composición
```

Criterios que se exigen antes de adoptar un cambio:

| Métrica | Criterio |
|---|---|
| Residual medio del top-1 | no bajar más de 2 % relativo |
| Diversidad (top-1 únicos) | subir o mantenerse |
| Estabilidad entre estados seguidos | no bajar más de 3 puntos |
| Latencia media | < 20 ms (hoy 4.5 ms) |
| Invariantes | 6/6, cero violaciones |

## UI

```bash
python3 herramientas/capturar_ui.py      # escribe capturas/ y falla si no puede pintar
python3 tests/test_ui.py                 # gate completo (preferencias, breakpoints, pintado)
```

| Comprobación | Criterio |
|---|---|
| Tamaños | 960×1080, 1280×720, 1920×1080, 800×600, sin recortes |
| RAM del panel | < 150 MB (hoy 127.5 MB) |
| CPU en reposo | < 2 % (hoy 0.2 %) |
| Ventana | recuerda tamaño y posición; 640×480 mínimo |
| Estados | conectando / sin partida / en vivo / congelado / lectura dudosa, todos explícitos |
| Copiloto | responde o dice "no tengo ese dato"; nunca inventa |

## Copiloto

```bash
curl -s localhost:8090/api/copiloto
curl -s -X POST localhost:8090/api/copiloto -H 'Content-Type: application/json' \
     -d '{"pregunta":"¿Qué compro ahora?"}'
```

| Comprobación | Criterio |
|---|---|
| Respuestas de muestra | 5 preguntas con estado real (`informes/copiloto-muestras.md`) |
| Presupuesto | la 6.ª llamada del minuto se rechaza |
| Caché | la misma pregunta con el mismo estado no gasta cuota |
| Datos congelados | lo dice antes de recomendar |
| Secretos | nunca se imprimen ni se escriben en el repo |

## Coherencia de estados (manual, cada cambio de UI)

- **Conectando**: se ve el esqueleto, nada de ítems viejos.
- **Sin partida**: mensaje claro, indicador apagado, sin datos falsos.
- **En vivo**: hora, almas y ventaja actualizadas; recomendación estable.
- **Datos congelados**: insignia naranja con la edad de los datos.
- **Lectura dudosa**: título explícito, confianza baja, se mantiene la última buena.
- **Fase inicial**: no inventa compras; dice que aún no toca.

Regla de oro: **el panel nunca muestra un dato que no pueda respaldar**. Si no lee, lo dice.

## Señales de alarma

Si aparece cualquiera de estas, algo se degradó y hay que parar:

1. El panel dice "en vivo" con datos de hace más de 10 s.
2. Una recomendación sale sin razones (invariante 5).
3. La recomendación cambia dos veces en menos de 10 s de partida (invariante 3).
4. El copiloto responde cifras que no están en el estado ni en una fuente.
5. `evaluar_motor.py` baja la diversidad por debajo de 15 ítems distintos.
6. El panel pasa de 150 MB o de 2 % de CPU en reposo.

## Cómo volver atrás

```bash
git log --oneline                              # baseline-9h = estado de partida
git diff baseline-9h --stat
git checkout baseline-9h -- coach/ run.py panel_nativo.py
```

Banderas en `config/coach.yaml`: `patrones_nuevos`, `copiloto`, `hud_ocr`,
`archivado_auto`, `interfaz_responsive`.
