# Demostración de Spain Open Data 0.6.0

[Ver la grabación del conector alojado](https://github.com/samihalawa/spain-assistant-mcp-apps/releases/download/v0.6.1/spain-hosted-demo.mp4).

La grabación muestra una interfaz de anfitrión SDK con paquetes 0.6.0 y el servidor alojado 0.6.1. Incluye resultados reales de las siete herramientas; muestra un fallo temporal de Catastro y su recuperación posterior. Se editaron las pausas. No es una grabación de ChatGPT o Claude ni una demostración de selección de herramientas por un modelo.

## Guion de reproducción

Este guion describe pasos reproducibles; es distinto de la grabación enlazada.

1. Instala el paquete 0.6.0 en un anfitrión compatible y conecta el endpoint MCP remoto acotado.
2. Formula un caso positivo de `docs/review-cases.json` con sus identificadores y límites.
3. Observa la llamada real a `compare_spanish_open_datasets` y los datos, fuentes, fechas y cobertura devueltos. Distingue resultados parciales y errores de fuente de una búsqueda sin coincidencias.
4. Usa otro caso para revisar una variación de entrada o un límite del resultado.
5. En una sesión de asistente, formula un caso negativo y comprueba que explica el límite sin invocar la herramienta ni afirmar una acción completada. Este paso no queda acreditado por la demostración SDK.

Las capturas estáticas de versiones anteriores siguen siendo ejemplos históricos con su fecha original y no sustituyen la grabación del conector.
