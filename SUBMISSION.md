# Claude review — Spain Open Data 0.2.0

Publisher: Sami Halawa · Contact: sami@samihalawa.com

Repository: https://github.com/samihalawa/spain-open-data

Plugin at repository root. Stable identity: `spain-open-data`.

## Listing

Encuentra datasets españoles y compara publicador, formatos, licencia y fecha antes de integrarlos en tu trabajo.

Audience: Desarrolladores y equipos que buscan datos públicos reutilizables.

First prompt: Busca datasets de empleo y compáralos por formato, licencia y fecha.

## Reviewer walkthrough

Install with `/plugin install spain-open-data --marketplace samihalawa/spain-open-data`. Ask for an example: `demo` must be labelled as a saved snapshot, not live. The captured response is in `skills/spain-open-data/references/demo.json`. Run the live README example in an authorized Python 3.11+ environment, inspect scope and source dates, then export HTML. The report must not execute source text or load external assets.

Negative fixtures in `tests/test_core.py` are synthetic regressions, not live user tests. No credentials, product account, purchase or API key is required. This is a skills package, not a hosted MCP service.

## Included review materials

README, CHANGELOG, real icon, support/privacy/terms, static page source in docs/, saved official-source example, executable tests and versioned evidence. Dataset/service rights are separate from the MIT software licence.

## Scope

No descarga automáticamente distribuciones externas ni ejecuta archivos. No garantiza licencias o descargas vigentes. La fecha del catálogo no equivale al periodo del dato.

Read evidence for the actual completed checks. CI is an inactive template. Source publication, package validation, installation, user acceptance, directory review and adoption are separate states. No official listing or approval is claimed. Submit through https://claude.ai/directory/manage under the intended verified publisher identity; applicable publisher attestations remain with the owner.
