import csv, argparse, json
from pathlib import Path
from .url_manager import read_rows

def main():
    p=argparse.ArgumentParser(description='Export source registry for teammates')
    p.add_argument('--file',default='urls.csv')
    p.add_argument('--output',default='output/source_registry.json')
    p.add_argument('--include-directory',action='store_true')
    a=p.parse_args()
    rows=read_rows(a.file)
    if not a.include_directory:
        rows=[r for r in rows if r.get('source_role')!='discovery']
    for r in rows:
        r['enabled']=r.get('enabled','true').lower() in ('true','1','yes')
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'匯出 {len(rows)} 筆到 {out}')
if __name__=='__main__':main()
