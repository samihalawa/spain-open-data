# Spain Open Data

Consulta metadatos de datos.gob.es por término y página; compara publicador, formatos, licencia y lagunas sin afirmar inspección de las distribuciones.

**Versión 0.6.3 · Conector MCP alojado e instrucciones complementarias · Sami Halawa · MIT**

## Instalación y uso

```bash
/plugin install spain-open-data --marketplace samihalawa/2026-MASTER-Marketplace-Plugins-Connectors-etc
```


Instala el paquete en un anfitrión compatible con plugins y MCP remoto. La configuración incluida conecta `https://aiplugins.megawebs.com/mcp/spain-open-data` mediante Streamable HTTP y expone `compare_spanish_open_datasets`. No necesitas Python local, instalar dependencias ni proporcionar una clave del editor. La disponibilidad de la conexión depende del anfitrión y de la fuente pública.

> Busca hasta seis conjuntos de datos de vivienda en la primera página de datos.gob.es y cita sus fichas.

- Busca movilidad en la página de índice 1 de datos.gob.es, con un máximo de cuatro registros.
- Busca hasta doce conjuntos de datos de empleo y compara los publicadores y formatos que declara el catálogo.

Lee [la habilidad](skills/spain-open-data/SKILL.md) para el procedimiento, [las fuentes](skills/spain-open-data/references/sources.md) y [el contrato de acceso](skills/spain-open-data/references/runtime.md). La herramienta realiza la consulta acotada descrita; la lectura de documentos, interpretación y creación de archivos usan capacidades adicionales del anfitrión. Conserva los identificadores, enlaces, fechas y límites realmente devueltos.

## Alcance

No presenta solicitudes u ofertas, no firma, no compra, no consulta datos protegidos ni activa vigilancia. Una respuesta parcial o fallida no prueba ausencia de registros. No se garantiza elegibilidad, resultado jurídico, titularidad ni financiación.

Los [ejemplos guardados](examples/demo.md) son capturas históricas de versiones anteriores, no consultas actuales. El historial de 0.5.0 conserva la edición de instrucciones; 0.6.0 añade una conexión remota explícita y no reetiqueta esas capturas. La aprobación en un directorio se verifica por separado.

[Producto e instalación](https://aiplugins.megawebs.com/plugins/spain-open-data) · [Privacidad](https://aiplugins.megawebs.com/plugins/spain-open-data/privacy) · [Condiciones](https://aiplugins.megawebs.com/plugins/spain-open-data/terms) · [Soporte](https://aiplugins.megawebs.com/plugins/spain-open-data/support)
