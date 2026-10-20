"""Deterministic regressions: fixtures are synthetic and never contact a provider."""
from pathlib import Path
import datetime as dt
import json
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SLUG=json.loads((ROOT/'plugin.json').read_text())['name']
sys.path.insert(0,str(ROOT/'skills'/SLUG/'scripts'))
from spain_suite import core as c
from spain_suite.presentation import render, safe_link, value
NOW='2026-10-20T12:00:00+00:00'

def response(body,url='https://www.boe.es/test'):
    raw=body if isinstance(body,bytes) else body.encode() if isinstance(body,str) else json.dumps(body).encode()
    return c.Fetch(raw,url,NOW,'application/json')

def feed(n=3,extra='',bad_deadline=False):
    entries=[]
    for i in range(n):
        deadline='' if bad_deadline and i==0 else '<cbc:EndDate>2026-12-01</cbc:EndDate>'
        entries.append(f'''<entry><id>tender-{i}</id><title>Software {i}</title><updated>2026-10-20</updated><link href="https://contrataciondelestado.es/test/{i}"/><cac:ContractFolderStatus><cbc:ContractFolderID>REF-{i}</cbc:ContractFolderID><cbc:ContractFolderStatusCode>PUB</cbc:ContractFolderStatusCode><cac:ProcurementProject><cac:RequiredCommodityClassification><cbc:ItemClassificationCode>72000000</cbc:ItemClassificationCode></cac:RequiredCommodityClassification></cac:ProcurementProject><cac:TenderSubmissionDeadlinePeriod>{deadline}</cac:TenderSubmissionDeadlinePeriod></cac:ContractFolderStatus></entry>''')
    return response('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cac="urn:cac" xmlns:cbc="urn:cbc" xmlns:at="http://purl.org/atompub/tombstones/1.0">'+''.join(entries)+extra+'</feed>',c.PLACSP)

class InputSafety(unittest.TestCase):
    def test_https_official_allowed(self):self.assertEqual(c.safe_url('https://www.boe.es/a?x=1'),'https://www.boe.es/a?x=1')
    def test_untrusted_urls_rejected(self):
        for url in ['http://www.boe.es/','https://127.0.0.1/','https://www.boe.es.evil.invalid/','https://user:pass@www.boe.es/','https://www.boe.es:444/','https://www.boe.es/#frag','https://[bad','https://www.boe.es/\n',None]:
            with self.subTest(url=url),self.assertRaises(c.SourceError):c.safe_url(url)
    def test_utf8_entities_rejected(self):
        with self.assertRaises(c.SourceError):response(b'<!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>').xml()
    def test_utf16_entities_rejected(self):
        with self.assertRaises(c.SourceError):response('<!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>'.encode('utf-16')).xml()
    def test_plain_xml_works(self):self.assertEqual(response('<a>good</a>').xml().text,'good')
    def test_unhashable_tool_name_is_error(self):self.assertFalse(c.call_tool([],{}).get('ok'))
    def test_nonobject_arguments_is_error(self):self.assertFalse(c.call_tool('licita_search',[]).get('ok'))
    def test_boolean_integer_rejected(self):self.assertFalse(c.call_tool('ine_operations',{'limit':True})['ok'])
    def test_invalid_calendar_date(self):self.assertFalse(c.call_tool('boe_daily',{'date':'2026-02-31'})['ok'])
    def test_oversized_query(self):self.assertFalse(c.call_tool('ayudas_search',{'query':'a'*1000})['ok'])
    def test_cross_host_cursor(self):self.assertFalse(c.call_tool('licita_search',{'cursor':'https://www.boe.es/a.atom'})['ok'])
    def test_negative_offset(self):self.assertFalse(c.call_tool('ine_tables',{'operation_id':1,'offset':-1})['ok'])

class ProviderSchemas(unittest.TestCase):
    def test_boe_bad_payload_is_not_empty(self):
        with patch.object(c.CLIENT,'get',return_value=response({})):r=c.call_tool('boe_daily',{'date':'2026-10-19'})
        self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'schema_changed')
    def test_boe_embedded_error(self):
        with patch.object(c.CLIENT,'get',return_value=response({'status':{'code':'404'}})):r=c.call_tool('boe_daily',{'date':'2026-10-19'})
        self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'source_not_found')
    def test_borme_bad_payload_is_not_empty(self):
        with patch.object(c.CLIENT,'get',return_value=response({})):r=c.call_tool('borme_company_notices',{'company':'Example SA','date':'2026-10-19'})
        self.assertFalse(r['ok'])
    def test_catalog_bad_payload_is_not_empty(self):
        with patch.object(c.CLIENT,'get',return_value=response({})):r=c.call_tool('open_data_search',{'query':'empleo'})
        self.assertFalse(r['ok'])
    def test_catalog_genuine_empty_is_valid(self):
        with patch.object(c.CLIENT,'get',return_value=response({'result':{'items':[]}})):r=c.call_tool('open_data_search',{'query':'empleo'})
        self.assertTrue(r['ok']);self.assertEqual(r['data'],[])
    def test_dataset_slug_returned(self):self.assertEqual(c.normalize_dataset({'_about':'https://datos.gob.es/catalogo/test-data'})['dataset_id'],'test-data')
    def test_bdns_wrong_identity(self):
        with patch.object(c.CLIENT,'get',return_value=response({'codigoBDNS':'22'})):r=c.call_tool('ayudas_call',{'bdns_number':'11'})
        self.assertFalse(r['ok'])
    def test_catastro_reported_error(self):
        with patch.object(c.CLIENT,'get',return_value=response({'consulta_dnprcResult':{'lerr':[{'err':1}]}})):r=c.call_tool('catastro_property',{'reference':'2749704YJ0624N0001DI'})
        self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'source_reported_error')
    def test_catastro_empty_response_error(self):
        with patch.object(c.CLIENT,'get',return_value=response({'consulta_dnprcResult':{}})):r=c.call_tool('catastro_property',{'reference':'2749704YJ0624N0001DI'})
        self.assertFalse(r['ok'])
    def test_catastro_multiple_candidates_preserved(self):
        with patch.object(c.CLIENT,'get',return_value=response({'consulta_dnprcResult':{'lrcdnp':[{'rc':'a'},{'rc':'b'}]}})):r=c.call_tool('catastro_property',{'reference':'2749704YJ0624N'})
        self.assertTrue(r['ok']);self.assertFalse(r['coverage']['single_property']);self.assertEqual(len(r['data']['candidate_properties']),2)
    def test_coordinates_label_axes(self):
        body={'Consulta_CPMRCResult':{'coordenadas':{'coord':[{'geo':{'xcen':'-3.7','ycen':'40.4','srs':'EPSG:4326'}}]}}}
        with patch.object(c.CLIENT,'get',return_value=response(body)):r=c.call_tool('catastro_coordinates',{'reference':'2749704YJ0624N'})
        self.assertTrue(r['ok']);self.assertEqual(r['data']['points'][0]['longitude'],-3.7);self.assertEqual(r['data']['points'][0]['latitude'],40.4)
    def test_coordinates_reject_bad_crs_and_numbers(self):
        for geo in [{'xcen':'-3','ycen':'40','srs':'EPSG:3857'},{'xcen':'NaN','ycen':'40','srs':'EPSG:4326'},{'xcen':'0','ycen':'100','srs':'EPSG:4326'}]:
            with self.subTest(geo=geo),patch.object(c.CLIENT,'get',return_value=response({'Consulta_CPMRCResult':{'coordenadas':{'coord':[{'geo':geo}]}}})):r=c.call_tool('catastro_coordinates',{'reference':'2749704YJ0624N'})
            self.assertFalse(r['ok'])

class Pagination(unittest.TestCase):
    def test_tender_later_page_failure_preserves_results(self):
        next_url=c.PLACSP.replace('.atom','_20261019_201708.atom')
        first=feed(n=1,extra='<link rel="next" href="'+next_url+'"/>')
        with patch.object(c.CLIENT,'get',side_effect=[first,c.SourceError('response_too_large','Page exceeds cap',next_url)]):r=c.licita_search(max_pages=2)
        self.assertEqual(len(r['data']),1);self.assertTrue(r['coverage']['partial']);self.assertEqual(r['coverage']['next_cursor'],next_url);self.assertEqual(r['errors'][0]['code'],'response_too_large')
    def test_tender_continuation_drops_no_match(self):
        ids=[];args={'limit':1}
        with patch.object(c.CLIENT,'get',return_value=feed()):
            for _ in range(5):
                r=c.licita_search(**args);ids.extend(x['id'] for x in r['data']);args=r['coverage']['next_request']
                if not args:break
        self.assertEqual(ids,['tender-0','tender-1','tender-2']);self.assertIsNone(args)
    def test_tender_cancellation_applies(self):
        with patch.object(c.CLIENT,'get',return_value=feed(extra='<at:deleted-entry ref="tender-1"/>')):r=c.licita_search()
        self.assertEqual([x['id'] for x in r['data']],['tender-0','tender-2'])
    def test_tender_deadline_unknown_excluded_and_counted(self):
        with patch.object(c.CLIENT,'get',return_value=feed(bad_deadline=True)):r=c.licita_search(deadline_from='2026-10-20')
        self.assertEqual(len(r['data']),2);self.assertEqual(r['coverage']['unknown_deadlines_excluded'],1)
    def test_tender_wrong_xml_not_empty(self):
        with patch.object(c.CLIENT,'get',return_value=response('<html/>')):r=c.call_tool('licita_search',{})
        self.assertFalse(r['ok'])
    def test_tender_bad_next_link(self):
        with patch.object(c.CLIENT,'get',return_value=feed(extra='<link rel="next" href="https://www.boe.es/a.atom"/>')):r=c.call_tool('licita_search',{'max_pages':2})
        self.assertFalse(r['ok'])
    def test_ine_series_within_page_before_next_page(self):
        body=[{'Id':x,'Nombre':f'Example {x}','COD':f'ABC{x}'} for x in range(3)]
        with patch.object(c.CLIENT,'get',return_value=response(body)):
            a=c.ine_table_series(1,limit=1);b=c.ine_table_series(1,limit=1,offset=a['coverage']['next_offset']);d=c.ine_table_series(1,limit=1,offset=2)
        self.assertEqual([a['data'][0]['Id'],b['data'][0]['Id'],d['data'][0]['Id']],[0,1,2]);self.assertEqual(a['coverage']['next_page'],1);self.assertEqual(d['coverage']['next_page'],2)
    def test_ine_operations_offset(self):
        with patch.object(c.CLIENT,'get',return_value=response([{'Id':1,'Nombre':'One'},{'Id':2,'Nombre':'Two'}])):r=c.ine_operations(limit=1,offset=1)
        self.assertEqual(r['data'][0]['Id'],2);self.assertIsNone(r['coverage']['next_offset'])

class DomainLogic(unittest.TestCase):
    def test_date_only_does_not_certify_open(self):
        r=c.deadline_assessment('2026-10-01','2026-10-30','2026-10-20');self.assertEqual(r['date_state'],'within_published_dates');self.assertFalse(r['eligibility_verified']);self.assertFalse(r['portal_status_verified'])
    def test_closing_today_requires_time(self):self.assertEqual(c.deadline_assessment(end='2026-10-20',as_of='2026-10-20')['date_state'],'ends_today_check_time')
    def test_bad_and_conflicting_dates(self):
        self.assertEqual(c.deadline_assessment('2026-11-01','2026-10-01','2026-10-20')['date_state'],'conflicting_dates')
        self.assertEqual(c.deadline_assessment(end='tomorrow')['date_state'],'unrecognized_date')
    def test_missing_deadline_not_open(self):self.assertEqual(c.deadline_assessment()['date_state'],'deadline_not_established')
    def test_grant_shortlist_direct_award_and_zero_budget(self):
        search={'ok':True,'data':[{'bdns_number':'11','title':'Test'}],'sources':[],'warnings':[],'coverage':{'page':0}}
        detail={'ok':True,'data':{'codigoBDNS':'11','descripcion':'Subvención nominativa','presupuestoTotal':0,'abierto':False,'fechaInicioSolicitud':'2026-10-01','fechaFinSolicitud':'2026-10-30'},'sources':[]}
        with patch.object(c,'ayudas_search',return_value=search),patch.object(c,'ayudas_call',return_value=detail):r=c.ayudas_shortlist('test',as_of='2026-10-20')
        row=r['data'][0];self.assertTrue(row['direct_award_signal']);self.assertEqual(row['budget_total_eur'],0);self.assertIs(row['raw_abierto'],False);self.assertFalse(row['deadline_assessment']['portal_status_verified'])
    def test_grant_shortlist_partial_failure_visible(self):
        search={'ok':True,'data':[{'bdns_number':'11'}],'sources':[],'warnings':[],'coverage':{}}
        with patch.object(c,'ayudas_search',return_value=search),patch.object(c,'ayudas_call',side_effect=c.SourceError('source_unavailable','fixture unavailable')):r=c.ayudas_shortlist('test')
        self.assertTrue(r['coverage']['partial']);self.assertIn('detail_error',r['data'][0]);self.assertEqual(r['coverage']['details_checked'],0)
    def test_borme_range_partial_day_preserved(self):
        valid={'ok':True,'data':[],'sources':[],'coverage':{'matches':0,'documents_scanned':1}}
        with patch.object(c,'borme_company_notices',side_effect=[valid,c.SourceError('source_not_found','No issue')]):r=c.borme_company_range('Example','2026-10-19','2026-10-20')
        self.assertTrue(r['ok']);self.assertTrue(r['coverage']['partial']);self.assertEqual(r['coverage']['days'][1]['status'],'unavailable')
    def test_borme_all_days_failed_is_error(self):
        with patch.object(c,'borme_company_notices',side_effect=c.SourceError('source_unavailable','Unavailable')):r=c.borme_company_range('Example','2026-10-19','2026-10-20')
        self.assertFalse(r['ok']);self.assertEqual(len(r['errors']),2)
    def test_borme_range_bounds(self):
        self.assertFalse(c.call_tool('borme_company_range',{'company':'ABC','start_date':'2026-10-01','end_date':'2026-10-20'})['ok'])
        self.assertFalse(c.call_tool('borme_company_range',{'company':'A','start_date':'2026-10-19','end_date':'2026-10-20'})['ok'])
    def test_boe_compare_exposes_texts_and_dates(self):
        law=response('<response><data><texto><bloque id="a1"><version fecha_vigencia="20200101"><p>Before</p></version><version fecha_vigencia="20250101"><p>After</p></version></bloque></texto></data></response>')
        with patch.object(c.CLIENT,'get',return_value=law):r=c.boe_compare('BOE-A-2020-1','a1','2020-01-02','2026-01-01')
        self.assertTrue(r['data']['changed']);self.assertEqual(r['data']['older_text'],'Before');self.assertEqual(r['data']['newer_text'],'After')
    def test_boe_unavailable_version_not_substituted(self):
        law=response('<response><bloque id="a1"><version fecha_vigencia="20250101"><p>After</p></version></bloque></response>')
        with patch.object(c.CLIENT,'get',return_value=law):r=c.call_tool('boe_compare',{'law_id':'BOE-A-2020-1','block_id':'a1','older_date':'2020-01-01','newer_date':'2026-01-01'})
        self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'version_unavailable')
    def test_ine_zero_and_iso_period_preserved(self):
        body={'COD':'ABC1','Data':[{'Fecha':'2026-10-01T00:00:00+02:00','Valor':0}]}
        with patch.object(c.CLIENT,'get',return_value=response(body)):r=c.ine_series('ABC1')
        self.assertEqual(r['data']['Data'][0]['Valor'],0);self.assertEqual(r['coverage']['latest_observation_date'],'2026-10-01')

class Presentation(unittest.TestCase):
    def test_zero_false_not_missing(self):self.assertEqual(value(0),'0');self.assertEqual(value(False),'No');self.assertEqual(value(None),'No consta')
    def test_html_escapes_source_text(self):
        r={'ok':True,'data':[{'id':'X','title':'<script>alert(1)</script>','html_url':'javascript:alert(1)'}],'coverage':{},'warnings':['<img src=x onerror=evil()>']}
        out=render(r,'boe_daily',{'name':'Test'},'html');self.assertNotIn('<script>',out);self.assertNotIn('<img src=x',out);self.assertNotIn('href="javascript:',out);self.assertIn('&lt;script&gt;',out)
    def test_reject_javascript_links(self):self.assertIsNone(safe_link('javascript:alert(1)'));self.assertIsNone(safe_link('https://a:b@host/'))
    def test_saved_demo_label_is_prominent(self):
        out=render({'ok':True,'data':[],'example':{'captured_at':NOW}},'licita_search',{'name':'Test'},'html');self.assertIn('EJEMPLO GUARDADO',out);self.assertIn('no es una consulta en tiempo real',out)
    def test_error_not_empty_search(self):
        out=render({'ok':False,'error':{'code':'source_unavailable'}},'licita_search',{'name':'Test'},'markdown');self.assertIn('FUENTE NO COMPROBADA',out);self.assertNotIn('No se han encontrado coincidencias',out)
    def test_partial_label(self):
        out=render({'ok':True,'data':[],'coverage':{'partial':True}},'ayudas_shortlist',{'name':'Test'},'html');self.assertIn('RESULTADO PARCIAL',out)
    def test_source_timestamp_and_hash(self):
        r={'ok':True,'data':[],'sources':[{'url':'https://www.boe.es/test','retrieved_at':NOW,'sha256':'a'*64}]}
        out=render(r,'boe_daily',{'name':'Test'},'html');self.assertIn(NOW,out);self.assertIn('a'*16,out)
    def test_render_performs_no_fetch(self):
        with patch.object(c.CLIENT,'get',side_effect=AssertionError('Network forbidden')):self.assertIn('Test',render({'ok':True,'data':[]},'boe_daily',{'name':'Test'}))

if __name__=='__main__':unittest.main()
