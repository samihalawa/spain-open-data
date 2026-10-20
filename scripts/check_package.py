from pathlib import Path
import json,sys,subprocess,struct
root=Path(__file__).resolve().parents[1]
m=json.loads((root/'.claude-plugin/plugin.json').read_text());slug=m['name']
p=json.loads((root/'plugin.json').read_text())
assert p['name']==slug and p['version']==m['version']
assert m['author']['name']=='Sami Halawa' and m['license']=='MIT'
for k in ('documentationUrl','supportUrl','privacyPolicyUrl','termsOfServiceUrl'):
 assert m[k].startswith('https://github.com/samihalawa/'+slug+'/blob/main/')
for n in ('README.md','LICENSE','PRIVACY.md','TERMS.md','SUPPORT.md','SECURITY.md','SUBMISSION.md'):
 assert (root/n).is_file() and (root/n).stat().st_size>30
icon=(root/'assets/icon.png').read_bytes()
assert icon[:8]==bytes([137,80,78,71,13,10,26,10]) and struct.unpack('>II',icon[16:24])==(512,512)
skill=root/'skills'/slug
assert ('name: '+slug) in (skill/'SKILL.md').read_text()
r=subprocess.run([sys.executable,str(skill/'scripts/run.py'),'list'],capture_output=True,text=True,check=True)
assert set(json.loads(r.stdout))=={slug}
sys.path.insert(0,str(skill/'scripts'))
from spain_suite import core
assert not core.call_tool('__unknown__',{})['ok']
assert not core.call_tool('catastro_property',{'reference':'invalid'})['ok']
assert not core.call_tool('open_data_dataset',{'dataset_id':'http://127.0.0.1/'})['ok']
assert not core.call_tool('boe_daily',{'date':'2026-02-31'})['ok']
assert not core.call_tool('ine_series',{'series_code':'IPC251852','last':999999})['ok']
assert not (root/'.app.json').exists()
assert not p.get('apps') and not p.get('extensions',{}).get('com.openai',{}).get('apps')
print('PASS: package structure, identity, policies, icon, scoped CLI and five error/input guards:',slug)
