# Demostración de Spain Open Data 0.6.0

Este documento es un guion, no una grabación ni prueba de ejecución.

1. En un anfitrión compatible, muestra el paquete 0.6.0 instalado y el endpoint remoto acotado.
2. Formula el primer caso positivo de `docs/review-cases.json`, con sus identificadores y límites.
3. Muestra la llamada real a `compare_spanish_open_datasets` y el resultado de la fuente, sin sustituirlo por la captura histórica. Conserva fecha, enlaces y cobertura; si hay un fallo, muéstralo como tal.
4. Formula otro caso con variación de entrada y muestra la interpretación de límites o datos parciales.
5. Formula uno de los casos negativos: el asistente debe explicar el límite sin llamar a la herramienta ni afirmar una acción completada.
6. Reproduce la grabación final y verifica legibilidad y ausencia de secretos. Publica solo la grabación real en una URL accesible a revisores antes de añadir `review.demo_recording_url`.

Una prueba de API demuestra el contrato del servidor; no demuestra por sí sola que el asistente elija la herramienta correctamente ni la renderización en un anfitrión.
