"""Deterministic, escaped reports. No model, scripts, remote assets or telemetry."""
from __future__ import annotations
import datetime as dt
import html
import json
import re
import urllib.parse
from typing import Any
from zoneinfo import ZoneInfo

STATES={"not_started_by_date":"Aún no ha comenzado por fecha","past_end_date":"Fecha de cierre superada","ends_today_check_time":"Cierra hoy: comprobar hora","within_published_dates":"Dentro de las fechas publicadas","end_date_ahead_start_unverified":"Cierre futuro; inicio por verificar","deadline_not_established":"Plazo no establecido","conflicting_dates":"Fechas contradictorias","unrecognized_date":"Fecha no reconocida"}
CSS='''*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#152234;font:16px/1.6 system-ui,-apple-system,sans-serif}main{max-width:1140px;margin:36px auto;padding:40px;background:white;border:1px solid #dce3ed;border-radius:20px}header{border-bottom:2px solid #e5ebf3;margin-bottom:30px;padding-bottom:24px}.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#45627d;font-weight:750}h1{font-size:clamp(30px,5vw,48px);line-height:1.12;letter-spacing:-.04em;margin:10px 0 16px}h2{font-size:21px;letter-spacing:-.02em;margin:30px 0 12px}p{max-width:78ch;overflow-wrap:anywhere}.badge{padding:12px 16px;background:#fff4d8;color:#634405;border-radius:9px;border:1px solid #e8cc7f}.notice{background:#eef5fb;padding:14px;border-radius:9px}table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;background:#edf3f9;color:#304962}td,th{padding:12px;border-bottom:1px solid #dce3ed;vertical-align:top}td{min-width:100px;overflow-wrap:anywhere}.scroll{overflow:auto;max-width:100%}a{color:#155b92;text-decoration-thickness:1px;text-underline-offset:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f8;padding:18px;border-radius:10px;font:13px/1.6 ui-monospace,monospace}details{margin:18px 0}summary{cursor:pointer;font-weight:650}small,footer{color:#526579}.source{margin:14px 0;overflow-wrap:anywhere}.error{border-left:4px solid #bd4036;padding:12px;background:#fff1ef}.muted{color:#526579}@media(max-width:650px){main{margin:0;border:0;border-radius:0;padding:24px 16px}td,th{padding:9px}}@media print{body{background:white}main{margin:0;border:0;padding:0;max-width:none}.scroll{overflow:visible}details{display:block}pre{font-size:10px}a{color:inherit}thead{display:table-header-group}tr{break-inside:avoid}}'''

def value(v: Any, maximum: int | None = None) -> str:
    if v is None or v=="":out="No consta"
    elif isinstance(v,bool):out="Sí" if v else "No"
    elif isinstance(v,(dict,list)):out=json.dumps(v,ensure_ascii=False)
    else:out=str(v)
    return out if maximum is None or len(out)<=maximum else out[:maximum]+"… [ver respuesta completa]"


def safe_link(url: Any) -> str | None:
    if not isinstance(url,str) or any(ord(c)<32 for c in url):return None
    try:
        p=urllib.parse.urlsplit(url)
        if p.scheme not in ("http","https") or not p.hostname or p.username or p.password:return None
        _=p.port
    except ValueError:return None
    return url


def cell(v: Any, fmt: str) -> str:
    text=value(v,1200);url=safe_link(v)
    if fmt=="html":
        return '<a href="'+html.escape(url,quote=True)+'" rel="noreferrer noopener">Fuente oficial</a>' if url else html.escape(text)
    text=html.escape(text).replace('\\','\\\\').replace('|','\\|').replace('\n','<br>').replace('[','\\[').replace(']','\\]').replace('`','\\`')
    return '[Fuente oficial]('+urllib.parse.quote(url,safe=':/?&=%#@!+,;-_~')+')' if url else text


def observation_date(v: Any) -> str:
    try:
        if isinstance(v,(int,float)) and not isinstance(v,bool):return dt.datetime.fromtimestamp(v/1000,ZoneInfo('Europe/Madrid')).date().isoformat()
        if isinstance(v,str):return dt.datetime.fromisoformat(v.replace('Z','+00:00')).date().isoformat()
    except (ValueError,OverflowError,OSError):pass
    return value(v)


def table_view(result: dict, tool: str):
    if tool=='catastro_ficha':result={**result,'data':result.get('data',{}).get('property',{})};tool='catastro_property'
    if tool=='ine_series_change':
        d=result.get('data',{});return ['Indicador','Valor'],[['Serie',d.get('series_name')],['Periodo anterior',d.get('older_period')],['Valor anterior',d.get('older_value')],['Periodo posterior',d.get('newer_period')],['Valor posterior',d.get('newer_value')],['Cambio absoluto',d.get('absolute_change')],['Cambio porcentual',d.get('percentage_change')],['Unidad',d.get('unit')]]
    if tool=='boe_find_articles':
        return ['Bloque','Título','Versión seleccionada','Extracto'],[[x.get('block_id'),x.get('title'),x.get('selected_version'),x.get('excerpt')] for x in result.get('data',[])]
    aliases={'licita_triage':'licita_search','ayudas_opportunities':'ayudas_shortlist','borme_events':'borme_company_range','open_data_compare':'open_data_search'}
    tool=aliases.get(tool,tool)
    data=result.get('data');rows=data if isinstance(data,list) else [data] if isinstance(data,dict) else []
    if tool=='licita_search':
        cols=['Expediente','Licitación','Organismo','Presupuesto sin IVA','Cierre publicado','Lectura del plazo','Enlace']
        out=[[r.get('reference'),r.get('title'),r.get('authority'),value(r.get('budget_excluding_tax'))+' '+value(r.get('currency')),value(r.get('deadline_date'))+' '+(r.get('deadline_time') or ''),STATES.get(r.get('deadline_assessment',{}).get('date_state'),'Comprobar plazo'),r.get('official_url')] for r in rows]
    elif tool in ('ayudas_search','ayudas_shortlist'):
        cols=['BDNS','Convocatoria','Fecha de cierre','Lectura del plazo','Tipo / señal','Enlace']
        out=[[r.get('bdns_number'),r.get('title'),r.get('deadline_assessment',{}).get('end_date'),STATES.get(r.get('deadline_assessment',{}).get('date_state'),'Detalle no comprobado' if r.get('detail_error') else 'Pendiente de comprobar'),'Posible concesión directa: revisar bases' if r.get('direct_award_signal') else r.get('call_type','Tipo por comprobar'),r.get('official_url')] for r in rows]
    elif tool=='ayudas_call':
        cols=['Campo','Dato publicado'];d=data or {};out=[['BDNS',d.get('codigoBDNS')],['Convocatoria',d.get('descripcion')],['Tipo',d.get('tipoConvocatoria')],['Inicio',d.get('fechaInicioSolicitud')],['Cierre',d.get('fechaFinSolicitud')],['Beneficiarios',d.get('tiposBeneficiarios')],['Bases',d.get('urlBasesReguladoras')],['Sede de solicitud',d.get('sedeElectronica')]]
    elif tool=='boe_compare':
        d=data or {};cols=['Campo','Resultado'];out=[['Norma',d.get('law_id')],['Artículo / bloque',d.get('block_id')],['Comparación',value(d.get('older_date'))+' → '+value(d.get('newer_date'))],['Cambió el texto',d.get('changed')],['Versión anterior',d.get('older_version')],['Versión posterior',d.get('newer_version')]]
    elif tool in ('boe_consolidated','boe_daily','boe_document'):
        cols=['Identificador','Título','Fecha / versión','Texto o enlace'];out=[[r.get('block_id',r.get('id')),r.get('title'),r.get('selected_version',r.get('publication_date',result.get('coverage',{}).get('date'))),r.get('text',r.get('html_url'))] for r in rows]
    elif tool.startswith('borme_company'):
        cols=['Sociedad y anuncio','Publicación','Provincia','Acto publicado','Enlace'];out=[[r.get('heading'),r.get('publication_date'),r.get('province'),r.get('text'),r.get('official_url')] for r in rows]
    elif tool=='catastro_property':
        d=data or {};cols=['Dato','Valor'];out=[['Referencia',d.get('reference')],['Dirección',d.get('address')],['Uso',d.get('use')],['Superficie construida (m²)',d.get('built_area_m2')],['Superficie de parcela (m²)',d.get('parcel_area_m2')],['Año de construcción',d.get('construction_year')],['Tipo de parcela',d.get('parcel_type')],['Mapa catastral',d.get('map_url')]]
        if d.get('candidate_properties'):out.append(['Varias unidades: elegir referencia completa',d['candidate_properties']])
    elif tool=='catastro_coordinates':
        cols=['Longitud','Latitud','Sistema','Referencia'];out=[[r.get('longitude'),r.get('latitude'),r.get('crs'),r.get('label')] for r in (data or {}).get('points',[])]
    elif tool=='ine_series':
        cols=['Periodo','Año','Valor','Estado','Unidad'];d=data or {};out=[[observation_date(r.get('Fecha')),r.get('Anyo'),r.get('Valor'),r.get('T3_TipoDato',r.get('FK_TipoDato')),d.get('T3_Unidad',d.get('FK_Unidad'))] for r in d.get('Data',[])]
    elif tool in ('ine_operations','ine_tables','ine_table_series'):
        cols=['Identificador','Nombre','Código'];out=[[r.get('Id'),r.get('Nombre'),r.get('COD',r.get('Codigo'))] for r in rows]
    elif tool.startswith('open_data'):
        cols=['Dataset','Publicador','Actualización del catálogo','Formatos','Licencia declarada','Catálogo'];out=[[r.get('title'),r.get('publisher'),r.get('modified'),', '.join(str(d.get('format') or '').rsplit('/',1)[-1] for d in r.get('distributions',[])),r.get('license'),r.get('catalog_url')] for r in rows]
    else:cols=['Resultado'];out=[[data]]
    return cols,out


def render(result: dict, tool: str, product: dict, fmt: str = 'markdown') -> str:
    if fmt=='json':return json.dumps(result,ensure_ascii=False,indent=2)
    title=product.get('name',tool);example=result.get('example',{});sources=result.get('sources',[])
    ok=result.get('ok') is True;partial=bool(result.get('coverage',{}).get('partial',False) or result.get('errors'))
    label='EJEMPLO GUARDADO · no es una consulta en tiempo real' if example else 'RESULTADO PARCIAL · revisar incidencias' if partial else 'CONSULTA A FUENTES OFICIALES' if ok else 'FUENTE NO COMPROBADA'
    intro=product.get('promise','Informe con evidencia y alcance explícitos.')
    cols,rows=table_view(result,tool) if ok else ([],[])
    status='La consulta es parcial y no muestra filas. No se puede concluir que no existan coincidencias; revisa las incidencias y la cobertura.' if ok and partial and not rows else 'No se han encontrado coincidencias dentro del alcance consultado.' if ok and not rows else 'La fuente no pudo comprobarse. No interpretes el error como cero resultados.' if not ok else f'{len(rows)} filas mostradas. La cobertura y las limitaciones se indican al final.'
    if fmt=='html':
        parts=['<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+' · Informe</title><style>'+CSS+'</style><body><main><header><div class="eyebrow">'+html.escape(title)+' / EVIDENCIA</div><h1>'+html.escape(title)+'</h1><p>'+html.escape(intro)+'</p><p class="badge">'+html.escape(label)+'</p></header><p class="notice">'+html.escape(status)+'</p>']
        if example:parts.append('<p>Captura: '+html.escape(value(example.get('captured_at')))+'. Reproduce el ejemplo con la herramienta de demostración del MCP declarado. Para datos actuales, solicita una consulta a ese MCP.</p>')
        if not ok:parts.append('<pre class="error">'+html.escape(json.dumps(result.get('error',{}),ensure_ascii=False,indent=2))+'</pre>')
        if rows:
            parts.append('<div class="scroll"><table><caption class="muted">Datos publicados; los textos extensos se abrevian en la tabla.</caption><thead><tr>'+''.join('<th scope="col">'+html.escape(c)+'</th>' for c in cols)+'</tr></thead><tbody>')
            parts.extend('<tr>'+''.join('<td>'+cell(v,'html')+'</td>' for v in row)+'</tr>' for row in rows);parts.append('</tbody></table></div>')
        if tool=='boe_compare' and ok:parts.append('<h2>Diferencia textual</h2><pre>'+html.escape(result['data'].get('unified_diff') or 'Sin cambios textuales en el bloque y fechas comparados.')+'</pre>')
        parts.append('<h2>Fuentes que puedes comprobar</h2>')
        for source in sources:
            partial_source=source.get('complete') is False
            hash_label='SHA-256 del prefijo' if partial_source else 'SHA-256'
            source_scope=(' · Respuesta incompleta: '+str(source.get('bytes_retained','?'))+' bytes conservados') if partial_source else ''
            url=safe_link(source.get('url'));link='<a href="'+html.escape(url,quote=True)+'" rel="noreferrer noopener">'+html.escape(url)+'</a>' if url else html.escape(value(source.get('url')))
            parts.append('<div class="source">'+link+'<br><small>Consulta: '+html.escape(value(source.get('retrieved_at')))+' · '+hash_label+': '+html.escape(value(source.get('sha256'))[:16])+'…'+html.escape(source_scope)+'</small></div>')
        parts.append('<h2>Alcance de esta consulta</h2><pre>'+html.escape(json.dumps(result.get('coverage',{}),ensure_ascii=False,indent=2))+'</pre>')
        if result.get('warnings'):parts.append('<details open><summary>Antes de tomar una decisión</summary>'+''.join('<p>'+html.escape(str(w))+'</p>' for w in result['warnings'])+'</details>')
        if result.get('errors'):parts.append('<pre class="error">'+html.escape(json.dumps(result['errors'],ensure_ascii=False,indent=2))+'</pre>')
        parts.append('<details><summary>Respuesta estructurada completa</summary><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details><footer>Software independiente de Sami Halawa. No es un servicio oficial ni una certificación. Este informe no ejecuta scripts ni carga recursos externos.</footer></main></body></html>')
        return '\n'.join(parts)
    parts=['# '+title,'',intro,'','> '+label,'',status,'']
    if example:parts+=['Captura guardada: '+value(example.get('captured_at'))+'.','']
    if rows:
        parts+=['| '+' | '.join(cols)+' |','|'+'|'.join('---' for _ in cols)+'|']
        parts+=['| '+' | '.join(cell(v,'markdown') for v in row)+' |' for row in rows]
    if not ok:parts+=['Error: '+value(result.get('error'))]
    if tool=='boe_compare' and ok:parts+=['','## Diferencia textual','', '    '+(result['data'].get('unified_diff') or 'Sin cambios textuales en el bloque y fechas comparados.').replace('\n','\n    ')]
    parts+=['','## Fuentes','']
    for source in sources:parts+=['- '+cell(source.get('url'),'markdown')+' · Consulta: '+value(source.get('retrieved_at'))+(' · Solo prefijo de respuesta: incompleta' if source.get('complete') is False else '')]
    parts+=['','## Alcance','', '    '+json.dumps(result.get('coverage',{}),ensure_ascii=False,indent=2).replace('\n','\n    ') ]
    if result.get('errors'):parts+=['','## Incidencias de la consulta','', '    '+json.dumps(result['errors'],ensure_ascii=False,indent=2).replace('\n','\n    ')]
    parts+=['','## Límites y comprobaciones','']+[ '- '+html.escape(str(w)) for w in result.get('warnings',[]) ]
    parts+=['','Software independiente de Sami Halawa. Conserva el JSON para inspeccionar todos los campos y textos completos.']
    return '\n'.join(parts)+'\n'
