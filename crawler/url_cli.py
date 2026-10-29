import argparse
from .url_manager import read_rows,add_url,update_url,delete_url

def main():
    p=argparse.ArgumentParser(description='觀音地方知識：網址管理')
    p.add_argument('--file',default='urls.csv')
    sub=p.add_subparsers(dest='command',required=True)
    listing=sub.add_parser('list');listing.add_argument('--origin',choices=['teacher','extra']);listing.add_argument('--all',action='store_true');listing.add_argument('--scope');listing.add_argument('--review')
    add=sub.add_parser('add');add.add_argument('url');add.add_argument('--title',default='');add.add_argument('--topic',default='');add.add_argument('--publisher',default='');add.add_argument('--notes',default='')
    update=sub.add_parser('update');update.add_argument('id');update.add_argument('--url');update.add_argument('--title');update.add_argument('--topic');update.add_argument('--publisher');update.add_argument('--notes');update.add_argument('--scope');update.add_argument('--review');update.add_argument('--role')
    for action in ('delete','disable','enable'):
        a=sub.add_parser(action);a.add_argument('id')
    args=p.parse_args()
    try:
        if args.command=='list':
            rows=read_rows(args.file)
            if args.origin:rows=[r for r in rows if r['origin']==args.origin]
            if args.scope:rows=[r for r in rows if r.get('geo_scope')==args.scope]
            if args.review:rows=[r for r in rows if r.get('review_status')==args.review]
            if not args.all:rows=[r for r in rows if r['enabled'].lower() not in ('false','no','0')]
            for r in rows:print(f"{r['id']:12} {r['origin']:7} {r['enabled']:5} {r['topic'][:10]:10} {r['url']}")
            print(f'共 {len(rows)} 筆')
        elif args.command=='add':print('新增成功：',add_url(args.file,args.url,args.title,args.topic,args.publisher,args.notes))
        elif args.command=='update':
            changes={key:value for key,value in vars(args).items() if key in {'url','title','topic','publisher','notes','scope','review','role'} and value is not None}
            if 'title' in changes:changes['title_hint']=changes.pop('title')
            if 'scope' in changes:changes['geo_scope']=changes.pop('scope')
            if 'review' in changes:changes['review_status']=changes.pop('review')
            if 'role' in changes:changes['source_role']=changes.pop('role')
            update_url(args.file,args.id,**changes);print('修改完成',args.id)
        elif args.command=='delete':delete_url(args.file,args.id);print('刪除完成',args.id)
        else:update_url(args.file,args.id,enabled='true' if args.command=='enable' else 'false');print(args.command,'完成',args.id)
    except ValueError as e:p.error(str(e))
if __name__=='__main__':main()
