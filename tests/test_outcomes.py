import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
slug=json.loads((root/'plugin.json').read_text())['name']
sys.path.insert(0,str(root/'skills'/slug/'scripts'))
from spain_suite import core as c
def ok(data):return {'ok':True,'data':data,'sources':[],'coverage':{},'warnings':[]}
class Workflows(unittest.TestCase):
 def test_oversized_initial_tender_page_is_not_a_query_failure(self):
  with patch.object(c.CLIENT,'get',side_effect=c.SourceError('response_too_large','too large',c.PLACSP)):
   result=c.call_tool('licita_triage',{'query':'software','limit':1})
  self.assertFalse(result['ok'])
  self.assertEqual(result['error']['code'],'response_too_large')
  self.assertIn('cannot reduce',result['error']['message'])
  self.assertNotIn('data',result)
 def test_triage(self):
  with patch.object(c,'licita_search',return_value=ok([{'id':'x','deadline_assessment':{'date_state':'past_end_date'}}])):
   r=c.licita_triage()
  self.assertEqual(r['data'][0]['review_bucket'],'published_deadline_passed')
 def test_grants(self):
  with patch.object(c,'ayudas_shortlist',return_value=ok([{'bdns_number':'x','direct_award_signal':True}])):
   r=c.ayudas_opportunities('IA')
  self.assertEqual(r['data'][0]['review_bucket'],'possible_direct_award')
 def test_articles(self):
  xml=b'<response><bloque id="a118" titulo="Articulo 118"><version fecha_vigencia="20200101"><p>Rule</p></version></bloque></response>'
  f=c.Fetch(xml,'https://www.boe.es/x','2026-10-20','application/xml')
  with patch.object(c.CLIENT,'get',return_value=f):r=c.boe_find_articles('BOE-A-2017-12902','Articulo 118',as_of='2026-10-20')
  self.assertEqual(r['data'][0]['block_id'],'a118')
 def test_borme(self):
  with patch.object(c,'borme_company_range',return_value=ok([{'text':'Cambio de domicilio social. Nombramientos.'}])):
   r=c.borme_events('Example','2026-10-19','2026-10-20')
  self.assertIn('registered_office_change',r['data'][0]['event_categories'])
 def test_property(self):
  with patch.object(c,'catastro_property',return_value=ok({'reference':'x'})),patch.object(c,'catastro_coordinates',side_effect=c.SourceError('source_unavailable','down')):
   r=c.catastro_ficha('2749704YJ0624N0001DI')
  self.assertTrue(r['coverage']['partial'])
 def test_stats(self):
  data={'Data':[{'Fecha':'2026-01-01','Valor':0},{'Fecha':'2026-02-01','Valor':10}]}
  with patch.object(c,'ine_series',return_value=ok(data)):r=c.ine_series_change('IPC251852')
  self.assertEqual(r['data']['absolute_change'],10)
  self.assertIsNone(r['data']['percentage_change'])
 def test_catalog(self):
  with patch.object(c,'open_data_search',return_value=ok([{'license':None,'modified':None,'distributions':[]}])):
   r=c.open_data_compare('empleo')
  self.assertFalse(r['data'][0]['reuse_rights_verified'])
  self.assertIn('licence_not_declared',r['data'][0]['catalog_metadata_gaps'])
 def test_distribution_without_url_is_a_metadata_gap(self):
  for distribution in [{'format':'CSV'}, {'download_url':None,'access_url':''}]:
   with self.subTest(distribution=distribution),patch.object(c,'open_data_search',return_value=ok([{'distributions':[distribution]}])):
    result=c.open_data_compare('empleo')
   self.assertIn('no_distribution_link',result['data'][0]['catalog_metadata_gaps'])
 def test_distribution_with_access_url_has_no_link_gap(self):
  with patch.object(c,'open_data_search',return_value=ok([{'distributions':[{'download_url':None,'access_url':'https://datos.gob.es/example'}]}])):
   result=c.open_data_compare('empleo')
  self.assertNotIn('no_distribution_link',result['data'][0]['catalog_metadata_gaps'])
 def test_distribution(self):
  expected={'licita-espana':'licita_triage','ayudas-espana':'ayudas_opportunities','boe-impact':'boe_find_articles','borme-intelligence':'borme_events','catastro-pro':'catastro_ficha','ine-evidence':'ine_series_change','spain-open-data':'open_data_compare'}
  self.assertIn(expected[slug],[f.__name__ for f in c.PRODUCT_TOOLS[slug]])
if __name__=='__main__':unittest.main()
