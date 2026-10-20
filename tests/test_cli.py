"""Exercise the packaged command-line interface with network access blocked."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
SLUG=json.loads((ROOT/'plugin.json').read_text())['name']
RUN=ROOT/'skills'/SLUG/'scripts/run.py'
class CommandLine(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        (self.dir/'sitecustomize.py').write_text('import socket\ndef blocked(*a,**kw): raise RuntimeError("Network disabled in offline CLI regression")\nsocket.create_connection=blocked\nsocket.socket.connect=blocked\n')
        self.env={**os.environ,'PYTHONPATH':str(self.dir),'PYTHONDONTWRITEBYTECODE':'1'}
    def tearDown(self):self.temp.cleanup()
    def call(self,*args,input=None):return subprocess.run([sys.executable,str(RUN),*args],capture_output=True,text=True,input=input,env=self.env,timeout=15)
    def test_list_is_product_scoped(self):
        r=self.call('list');self.assertEqual(r.returncode,0);self.assertEqual(set(json.loads(r.stdout)),{SLUG})
    def test_doctor_runs_offline(self):
        r=self.call('doctor');self.assertEqual(r.returncode,0);d=json.loads(r.stdout);self.assertEqual(d['version'],'0.2.0');self.assertFalse(d['network_tested']);self.assertTrue(d['offline_demo_present'])
    def test_demo_markdown_runs_offline(self):
        r=self.call('demo');self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('EJEMPLO GUARDADO',r.stdout)
    def test_demo_html_runs_offline(self):
        r=self.call('demo','--format','html');self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('<html lang="es">',r.stdout);self.assertNotIn('<script',r.stdout.lower())
    def test_demo_json_marks_not_live(self):
        r=self.call('demo','--format','json');self.assertEqual(r.returncode,0);self.assertFalse(json.loads(r.stdout)['example']['live'])
    def test_export_does_not_overwrite(self):
        path=self.dir/'report.html';path.write_text('KEEP')
        r=self.call('demo','--format','html','--output',str(path));self.assertNotEqual(r.returncode,0);self.assertEqual(path.read_text(),'KEEP')
    def test_explicit_force_overwrites(self):
        path=self.dir/'report.html';path.write_text('OLD')
        r=self.call('demo','--format','html','--output',str(path),'--force');self.assertEqual(r.returncode,0,r.stdout);self.assertIn('EJEMPLO GUARDADO',path.read_text())
    def test_force_needs_output(self):
        r=self.call('demo','--force');self.assertNotEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['error']['code'],'invalid_input')
    def test_invalid_json_stdin(self):
        tool=json.loads(self.call('list').stdout)[SLUG][0]['name'];r=self.call('call',tool,'--stdin',input='{broken')
        self.assertNotEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['error']['code'],'invalid_input')
    def test_nonfinite_json_rejected(self):
        tool=json.loads(self.call('list').stdout)[SLUG][0]['name'];r=self.call('call',tool,'--json','{"x":NaN}')
        self.assertNotEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['error']['code'],'invalid_input')
    def test_oversized_input_rejected(self):
        path=self.dir/'too-big.json';path.write_text(' '*1_048_577)
        tool=json.loads(self.call('list').stdout)[SLUG][0]['name'];r=self.call('call',tool,'--input',str(path))
        self.assertNotEqual(r.returncode,0);self.assertIn('1 MiB',r.stdout)
    def test_unavailable_tool_rejected_before_network(self):
        r=self.call('call','__unavailable__');self.assertNotEqual(r.returncode,0);self.assertIn('invalid choice',r.stderr)
if __name__=='__main__':unittest.main()
