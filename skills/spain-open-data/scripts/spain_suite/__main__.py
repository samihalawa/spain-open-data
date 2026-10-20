"""JSON CLI. Credentials are neither required nor accepted."""
import argparse
import inspect
import json
import sys
from pathlib import Path
from .core import PRODUCT_TOOLS, TOOLS, call_tool

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    c=sub.add_parser('call');c.add_argument('tool',choices=sorted(TOOLS))
    g=c.add_mutually_exclusive_group();g.add_argument('--json',default='{}');g.add_argument('--input',type=Path);g.add_argument('--stdin',action='store_true')
    args=p.parse_args()
    if args.command=='list':
        out={slug:[{'name':f.__name__,'signature':str(inspect.signature(f)),'description':f.__doc__} for f in fs] for slug,fs in PRODUCT_TOOLS.items()}
    else:
        try:
            raw=sys.stdin.read(1_048_577) if args.stdin else args.input.read_text() if args.input else args.json
            if len(raw)>1_048_576: raise ValueError('Input exceeds 1 MiB')
            out=call_tool(args.tool,json.loads(raw))
        except (ValueError,OSError) as exc:
            out={'ok':False,'error':{'code':'invalid_input','message':str(exc)}}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out.get('ok',True) else 1

if __name__=='__main__':
    raise SystemExit(main())
