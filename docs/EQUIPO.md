# El equipo: cómo trabajamos agentes y humano

Este documento no es decoración: es el contrato que hace que varias sesiones de agentes
produzcan trabajo verificable en vez de ruido. Se copia tal cual a otro proyecto cambiando
solo la sección 9.

## 1. Reglas duras

1. **Una afirmación, una medición.** Si no hay número, captura o prueba que lo respalde, se
   escribe «no verificado». Inventar una cifra es el único error imperdonable.
2. **Adversario, no porrista.** Cada entrega pasa por alguien cuyo trabajo es encontrar el
   error, no confirmar la idea. La pregunta no es «¿está bien?» sino «¿cómo está mal?».
3. **Alcance pequeño y archivos disjuntos.** Un agente, un directorio. Dos agentes
   editando el mismo archivo es cómo se pierden horas.
4. **Lo que no se puede reproducir no entra.** Comando, versión, y resultado esperado.
5. **Revertir es barato, mentir no.** Si algo falla, se dice y se revierte.
6. **El humano decide el rumbo; el agente decide el cómo.** No se cambia el objetivo sin
   pedirlo.
7. **Todo cambio deja una línea** en el changelog o en el informe. Sin línea, no existe.

## 2. Roles

| Rol | Qué decide | Qué entrega | No hace |
|---|---|---|---|
| **Dirección** (humano + agente principal) | Rumbo, prioridades, qué se publica | Plan del ciclo, revisión final | Escribir código a mano si hay un rol para eso |
| **Producto/UI** | Qué ve el usuario y dónde | HTML/GTK, capturas 1× y 2×, pruebas de contrato | Tocar el motor o los datos |
| **Datos** | Qué se ingiere y con qué calidad | Esquema, ingesta reproducible, conteos | Decidir el algoritmo |
| **Motor** | Cómo se puntúa y se elige | Estimador, artefacto, puertas G | Tocar la UI |
| **Investigación** | Qué se sabe del juego y de la comunidad | Informe con fuentes y huecos declarados | Afirmar sin fuente |
| **QA adversarial** | Si la entrega se sostiene | Lista de defectos con reproducción | Arreglar (se devuelve al dueño) |

## 3. Ciclo de un ciclo de trabajo

```
PLAN     dirección escribe 3 líneas: objetivo, criterio de aceptación, archivos
BUILD    un agente por rol, alcance disjunto
VERIFY   pruebas + captura + número; el dueño adjunta evidencia
REVIEW   QA adversarial busca el error (no la confirmación)
DECIDE   se acepta, se devuelve o se revierte; una línea en el changelog
```

Un ciclo no termina con «listo»: termina con **evidencia** o con **«no se pudo»**.

## 4. Prompt master (plantilla)

Todo subagente recibe esto, rellenado. Sin esto, el agente inventa alcance.

```
Eres <ROL> en <PROYECTO>. Español de México, directo.
Contexto mínimo: <2-4 líneas de lo que ya está hecho y verificado>.
Tarea acotada: <una sola cosa>.
Criterio de aceptación: <cómo se demuestra que está bien: comando, captura, número>.
Archivos que puedes tocar: <lista>. Todo lo demás es de solo lectura.
Prohibido: sudo, push, tocar el navegador del dueño, inventar cifras.
Entrega: <5-15 líneas> con rutas absolutas, evidencia y qué no pudiste verificar.
```

Reglas de redacción que sí importan con modelos pequeños/rápidos:

- **Un objetivo por prompt.** Dos objetivos = el segundo se pierde.
- **Criterio de aceptación explícito.** Si no se puede comprobar, no es una tarea.
- **Decir qué NO tocar.** Los agentes tocan de más cuando no se les acota.
- **Pedir el «no pude».** Sin esa válvula, inventan.
- **Formato de entrega fijo.** Se compara y se audita sin releer todo.

## 5. Puertas de verificación

| Puerta | Qué exige | Quién la aplica |
|---|---|---|
| P1 · Pruebas | Suite en verde o fallo declarado con nombre y motivo | Dueño |
| P2 · Captura | Cambio visual con imagen 1× y 2×, no descripción | Producto/UI |
| P3 · Número | Toda cifra con su fuente, n e intervalo | Motor/Datos |
| P4 · Reproducción | Comando exacto que repite el resultado | QA |
| P5 · Reversión | `git revert` limpio o el cambio no se acepta | QA |

## 6. Concurrencia

- **Máximo 3 agentes a la vez**, y nunca dos en el mismo árbol de archivos.
- El principal reserva `coach/ui/**`, `coach/motor.py`, `datos/**` y `data/**` para no
  chocar; los agentes trabajan en `herramientas/**`, `docs/**`, `informes/**` o en la PC.
- Un agente que se queda sin criterio de aceptación se detiene y pregunta; no adivina.
- La PC headless (`pc`, <pc-auxiliar>) es el recurso de cómputo por defecto: ingesta,
  pruebas pesadas, builds. El escritorio se reserva para pantalla y juego.

## 7. Presupuesto y parada

- Cada ciclo declara cuánto puede gastar (tiempo/tokens) y qué se lleva si se acaba.
- **Regla del 80 %**: al llegar al 80 % del presupuesto sin criterio cumplido, se entrega
  lo parcial con «no se pudo» y se devuelve al plan. No se estira a ciegas.
- Un agente que repite el mismo intento dos veces sin cambio de información se detiene:
  eso es un bucle, no trabajo.

## 8. Anti-patrones (lo que nos costó tiempo)

- **Confirmar la idea del jefe.** Un informe que solo dice «sí se puede» no vale nada.
- **Medir sobre el conjunto donde se ajustó.** Ya pasó: la ventaja del modelo se infló.
- **String replace que falla en silencio.** Ya pasó: un parche «aplicado» que no cambió
  nada. Por eso se mide el efecto, no la intención.
- **Interpretar un centinela como dato.** `vendido_t = 0` significa «no vendido»; leerlo al
  revés infló la tasa de venta al 100 %.
- **Confundir descriptivo con causal.** «Este ítem gana 54 %» no es «compra este ítem».
- **Dejar que el agente elija el alcance.** Siempre elige el más divertido, no el útil.

## 9. Llevarlo a otro proyecto

Ya no se copia a mano:

```bash
herramientas/nuevo-equipo.sh /ruta/al/proyecto "Nombre del proyecto"
```

Crea `docs/EQUIPO.md`, `docs/ESTADO-ACTUAL.md`, `docs/PUERTAS.md` y
`docs/PROMPT-MASTER.md` con el nombre y la fecha puestos, y **no sobrescribe** nada que
exista (sin `--forzar`). Las plantillas viven en `plantillas/equipo/` y son genéricas: no
tienen nada de Deadlock.

Después:

1. Rellena `ESTADO-ACTUAL.md` **antes** de lanzar agentes.
2. Cambia roles y puertas si el dominio lo pide; **no cambies las reglas 1, 2 y 6**.
3. Escribe el criterio de aceptación del primer ciclo.
4. Arranca con 2 agentes, no con 6. La concurrencia se gana, no se asume.
