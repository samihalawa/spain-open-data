"""Bounded PLACSP fallback: unexamined bytes must never become full coverage."""
import io,json,sys,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SLUG=json.loads((ROOT/'plugin.json').read_text())['name']
sys.path.insert(0,str(ROOT/'skills'/SLUG/'scripts'))
from spain_suite import core as c

NEXT=c.PLACSP.replace('.atom','_20261022_201913.atom')
def document():
 header=('<feed xmlns="http://www.w3.org/2005/Atom"><link rel="next" href="'+NEXT+'"/>').encode()
 entries=[f'<entry><id>tender-{i}</id><title>Software {i}</title><updated>2026-10-23</updated></entry>'.encode() for i in range(3)]
 return header,entries,header+b''.join(entries)+b'</feed>'
class HTTP(io.BytesIO):
 headers={'Content-Type':'application/atom+xml'}
 def geturl(self):return c.PLACSP
class BoundedFeed(unittest.TestCase):
 def fetch(self,body,cap,allowed=True,client=None):
  client=client or c.OfficialClient()
  response=HTTP(body)
  with patch.object(c,'MAX_BYTES',cap),patch.object(client.opener,'open',return_value=response):
   result=client.get(c.PLACSP,accept='application/atom+xml',allow_atom_prefix=allowed)
  return result
 def prefix(self):
  header,entries,body=document();cap=len(header)+len(entries[0])+len(entries[1])+len(entries[2])//2
  return self.fetch(body,cap),cap
 def test_default_fetch_still_rejects_oversized_body(self):
  _,_,body=document()
  with self.assertRaises(c.SourceError) as error:self.fetch(body,100,allowed=False)
  self.assertEqual(error.exception.code,'response_too_large')
 def test_complete_feed_is_not_marked_partial(self):
  _,_,body=document();f=self.fetch(body,len(body))
  self.assertTrue(f.complete);self.assertEqual(len(f.xml().findall('{http://www.w3.org/2005/Atom}entry')),3)
  self.assertNotIn('sha256_scope',f.provenance())
 def test_oversized_body_retains_only_complete_entries_and_prefix_hash(self):
  f,cap=self.prefix();root=f.xml()
  self.assertFalse(f.complete);self.assertEqual(len(f.body),cap)
  self.assertEqual([c.path_text(e,'id') for e in root if c.local_name(e.tag)=='entry'],['tender-0','tender-1'])
  self.assertEqual(f.provenance()['sha256_scope'],'response_prefix')
  self.assertEqual(f.provenance()['sha256'],hashlib.sha256(f.body).hexdigest())
  self.assertFalse(f.provenance()['complete'])
 def test_reports_label_partial_hashes_and_partial_results(self):
  f,_=self.prefix()
  with patch.object(c.CLIENT,'get',return_value=f):result=c.licita_search(limit=1)
  from spain_suite.presentation import render
  html=render(result,'licita_search',{'name':'Licita'},'html')
  markdown=render(result,'licita_search',{'name':'Licita'},'markdown')
  self.assertIn('RESULTADO PARCIAL',html)
  self.assertIn('SHA-256 del prefijo',html)
  self.assertIn('Respuesta incompleta',html)
  self.assertIn('Solo prefijo de respuesta: incompleta',markdown)
 def test_prefix_cache_cannot_bypass_a_later_full_read(self):
  client=c.OfficialClient();header,entries,body=document();cap=len(body)-20
  self.fetch(body,cap,client=client)
  with self.assertRaises(c.SourceError):self.fetch(body,cap,allowed=False,client=client)
 def test_partial_window_never_advances_over_unread_suffix(self):
  f,_=self.prefix()
  with patch.object(c.CLIENT,'get',return_value=f) as get:r=c.licita_search(max_pages=3,limit=20)
  self.assertEqual(get.call_count,1);self.assertTrue(r['coverage']['partial']);self.assertFalse(r['coverage']['exhaustive'])
  self.assertEqual(len(r['data']),2);self.assertIsNone(r['coverage']['next_request'])
  self.assertEqual(r['coverage']['older_page_cursor'],NEXT)
  self.assertEqual(r['coverage']['continuation_blocked_reason'],'unread_page_suffix')
  self.assertEqual(r['errors'][0]['code'],'response_prefix_only')
 def test_continuation_within_prefix_loses_no_observed_match(self):
  f,_=self.prefix()
  with patch.object(c.CLIENT,'get',return_value=f):
   first=c.licita_search(limit=1);second=c.licita_search(**first['coverage']['next_request'])
  self.assertEqual([first['data'][0]['id'],second['data'][0]['id']],['tender-0','tender-1'])
  self.assertIsNone(second['coverage']['next_request']);self.assertTrue(second['coverage']['partial'])
 def test_no_matches_does_not_claim_a_complete_empty_search(self):
  f,_=self.prefix()
  with patch.object(c.CLIENT,'get',return_value=f):r=c.licita_search(query='unmatched')
  self.assertEqual(r['data'],[]);self.assertTrue(r['coverage']['partial']);self.assertIn('tombstones',' '.join(r['warnings']))
 def test_partial_entry_and_unsafe_xml_are_not_salvaged(self):
  for body in [b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>unfinished',b'<!DOCTYPE feed [<!ENTITY x "bad">]><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>&x;</id></entry>']:
   with self.subTest(body=body),self.assertRaises(c.SourceError):c.Fetch(body,c.PLACSP,'2026-10-23','application/atom+xml',complete=False).xml()
 def test_prefix_mode_cannot_be_used_for_other_official_sources(self):
  client=c.OfficialClient()
  with self.assertRaises(c.SourceError):client.get('https://www.boe.es/a',accept='application/atom+xml',allow_atom_prefix=True)
 def test_truncated_multibyte_character_does_not_hide_completed_entries(self):
  head,entries,_=document();body=head+entries[0]+b'<entry><title>'+ 'á'.encode()[:1]
  root=c.Fetch(body,c.PLACSP,'2026-10-23','application/atom+xml',complete=False).xml()
  self.assertEqual(len(root.findall('{http://www.w3.org/2005/Atom}entry')),1)
if __name__=='__main__':unittest.main()
