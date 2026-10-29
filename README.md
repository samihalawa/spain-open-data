<p><img src="assets/icon.png" width="72" height="72" alt="Icono de Spain Open Data"></p>

# Spain Open Data

## Encuentra el dataset. Comprueba si te sirve.

Encuentra datasets españoles y compara publicador, formatos, licencia y fecha antes de integrarlos en tu trabajo.

**Para:** Desarrolladores y equipos que buscan datos públicos reutilizables.

**Fuente:** datos.gob.es · **Sin cuenta adicional ni API key** · **Python 3.11+** · **MIT**

### Qué obtienes

- Identificador del dataset reutilizable en la siguiente consulta.
- Publicador, formatos y licencia en una ficha comparable.
- Metadatos encontrados separados de un fichero realmente inspeccionado.

### Pruébalo con una pregunta

> Busca datasets de empleo y compáralos por formato, licencia y fecha.

También: “Encuentra datos de mi municipio y distingue catálogo, descarga e inspección real.”

[Ver el informe de ejemplo](examples/demo.md) · [Código de la página del producto](docs/index.html) · [Flujo completo](skills/spain-open-data/references/workflow.md)

La demostración es una **captura guardada de fuentes oficiales**, no una consulta actual. Conserva fecha, enlaces y alcance.

## Instalar en Claude Code

```text
/plugin install spain-open-data --marketplace samihalawa/spain-open-data
```

O desde terminal:

```bash
claude plugin marketplace add samihalawa/spain-open-data
claude plugin install spain-open-data@spain-open-data
```

Después, pregunta en lenguaje natural o invoca `/spain-open-data:spain-open-data`.

## Ver un resultado sin conexión

Desde una copia de este repositorio:

```bash
python3 skills/spain-open-data/scripts/run.py demo
python3 skills/spain-open-data/scripts/run.py demo --format html --output ejemplo.html
```

## Consultar y guardar un informe

```bash
python3 skills/spain-open-data/scripts/run.py report open_data_compare --json '{"query": "empleo", "page_size": 3}'
```

Añade `--format html --output informe.html` o `--format json`. No se sobrescriben archivos por defecto. `doctor` comprueba el entorno local sin consultar proveedores.

## Dónde funciona

| Entorno | Comportamiento |
|---|---|
| Claude Code / Codex con Python y red autorizada | Adaptadores e informes ejecutables. |
| ChatGPT con navegación/archivos | Flujo con herramientas nativas disponibles; no es un MCP alojado. |
| Sin red | Demo guardada o documentos aportados; no datos actuales inventados. |

## Alcance real

No descarga automáticamente distribuciones externas ni ejecuta archivos. No garantiza licencias o descargas vigentes. La fecha del catálogo no equivale al periodo del dato.

## Verificación

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_package.py
claude plugin validate --strict .claude-plugin/plugin.json
claude plugin validate --strict .
```

[Mejoras y crítica](CHANGELOG.md) · [Evidencia versionada](evidence/) · [Revisión de Claude](SUBMISSION.md). Los tests no equivalen a adopción. `ci/validate.yml` es una plantilla inactiva.

**English:** An independent workflow for Spanish official data, with a self-contained Python adapter, offline example and readable reports. Answer language follows the user.

**Sami Halawa** · Software independiente; sin afiliación oficial. [Privacidad](PRIVACY.md) · [Condiciones](TERMS.md) · [Soporte](SUPPORT.md) · [Seguridad](SECURITY.md).

## Datos enviados a servicios externos

Las consultas en vivo envían únicamente los parámetros públicos necesarios de la consulta a los servicios oficiales identificados en [Fuentes y endpoints](skills/spain-open-data/references/sources.md). El proveedor recibe esos parámetros y la dirección de red del entorno que ejecuta la consulta. No se envían credenciales, adjuntos, perfiles personales ni el historial de conversación. Estos accesos se realizan desde las herramientas autorizadas del anfitrión o los adaptadores Python locales; este paquete no declara un conector MCP alojado.

Las respuestas oficiales pueden contener nombres, direcciones u otros datos personales públicos. La caché local es solo de memoria, durante un máximo de cinco minutos mientras se ejecuta el proceso. Los resultados pueden permanecer en la conversación o en informes guardados explícitamente por el usuario; su conservación depende del anfitrión y del usuario. El editor no opera un servicio que reciba o almacene estos datos. Consulta [Privacidad](PRIVACY.md) para los detalles y los límites de reutilización.
