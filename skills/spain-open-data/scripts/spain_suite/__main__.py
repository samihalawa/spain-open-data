"""Consultas oficiales, informes legibles y ejemplos sin conexión. Python 3.11+."""
import argparse
import copy
import inspect
import json
import platform
import sys
from pathlib import Path
from . import core
from .presentation import render
MAX_INPUT=1_048_576

def read_bounded(path):
    with path.open('r',encoding='utf-8') as f:raw=f.read(MAX_INPUT+1)
    if len(raw)>MAX_INPUT:raise ValueError('El archivo supera 1 MiB.')
    return raw

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list',help='Funciones y argumentos disponibles')
    sub.add_parser('doctor',help='Comprueba el entorno local sin usar la red')
    for name in ('call','report','demo'):
        c=sub.add_parser(name,help={'call':'Respuesta JSON por defecto','report':'Informe Markdown por defecto','demo':'Ejemplo guardado; nunca consulta la red'}[name])
        if name!='demo':
            c.add_argument('tool',choices=sorted(core.TOOLS))
            g=c.add_mutually_exclusive_group();g.add_argument('--json',default='{}');g.add_argument('--input',type=Path);g.add_argument('--stdin',action='store_true')
        c.add_argument('--format',choices=['json','markdown','html'],default='json' if name=='call' else 'markdown')
        c.add_argument('--output',type=Path,help='Guarda el informe; no sobrescribe por defecto')
        c.add_argument('--force',action='store_true',help='Permite sobrescribir la ruta de --output')
    args=p.parse_args();references=Path(__file__).resolve().parents[2]/'references'
    config_path=references/'product.json';product=json.loads(config_path.read_text()) if config_path.exists() else {'name':next(iter(core.PRODUCT_TOOLS))}
    if args.command=='list':out={slug:[{'name':f.__name__,'signature':str(inspect.signature(f)),'description':f.__doc__} for f in fs] for slug,fs in core.PRODUCT_TOOLS.items()};print(json.dumps(out,ensure_ascii=False,indent=2));return 0
    if args.command=='doctor':
        out={'ok':sys.version_info>=(3,11),'version':core.VERSION,'python':platform.python_version(),'product':product['name'],'tools':sorted(core.TOOLS),'third_party_runtime_dependencies':[],'network_tested':False,'offline_demo_present':(references/'demo.json').is_file()};print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if out['ok'] else 1
    try:
        if args.force and not args.output:raise ValueError('--force requiere --output.')
        if args.command=='demo':
            snapshot=json.loads(read_bounded(references/'demo.json'));tool=snapshot['tool'];out=copy.deepcopy(snapshot['result']);out['example']={'captured_at':snapshot['captured_at'],'mode':'saved_official_snapshot','live':False}
        else:
            raw=sys.stdin.read(MAX_INPUT+1) if args.stdin else read_bounded(args.input) if args.input else args.json
            if len(raw)>MAX_INPUT:raise ValueError('La entrada supera 1 MiB.')
            def bad_constant(s):raise ValueError('No se admiten NaN ni Infinity.')
            arguments=json.loads(raw,parse_constant=bad_constant);tool=args.tool;out=core.call_tool(tool,arguments)
        content=render(out,tool,product,args.format)
        if args.output:
            with args.output.open('w' if args.force else 'x',encoding='utf-8') as f:f.write(content+'\n')
            print(json.dumps({'ok':out.get('ok',False),'output':str(args.output),'format':args.format},ensure_ascii=False))
        else:print(content)
        return 0 if out.get('ok') is True else 1
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps({'ok':False,'error':{'code':'invalid_input','message':str(exc)}},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
