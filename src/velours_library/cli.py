"""Command-line interface for Velour's shared offline library."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Optional,Sequence
from .catalog import Library,LibraryItem,Candidate

def build_parser():
    p=argparse.ArgumentParser(prog='velour',description="Velour's local-first knowledge library"); p.add_argument('--root',default='library-data'); s=p.add_subparsers(dest='command',required=True)
    def meta(q):
        q.add_argument('file'); q.add_argument('--title',required=True); q.add_argument('--source',required=True); q.add_argument('--source-uri'); q.add_argument('--trust',default='unknown'); q.add_argument('--language',default='en'); q.add_argument('--rights-note'); q.add_argument('--tag',action='append',default=[])
    meta(s.add_parser('stage',help='Quarantine a source file for review'))
    add=s.add_parser('add',help='Stage and immediately publish a source file'); meta(add); add.add_argument('--published-at')
    q=s.add_parser('publish'); q.add_argument('candidate_id'); q.add_argument('--published-at')
    q=s.add_parser('reject'); q.add_argument('candidate_id'); q.add_argument('--reason',required=True)
    q=s.add_parser('candidates'); q.add_argument('--state')
    for name in ('inspect','verify','remove'): q=s.add_parser(name); q.add_argument('identifier')
    q=s.add_parser('search'); q.add_argument('query'); q.add_argument('--limit',type=int,default=10)
    s.add_parser('list'); return p

def _item(i:LibraryItem): return {'item_id':i.item_id,'title':i.title,'source':i.source,'source_uri':i.source_uri,'trust_class':i.trust_class,'media_type':i.media_type,'language':i.language,'sha256':i.sha256,'storage_path':i.storage_path,'extracted_text_path':i.extracted_text_path,'imported_at':i.imported_at,'published_at':i.published_at,'rights_note':i.rights_note,'tags':list(i.tags)}
def _cand(c:Candidate): return {'candidate_id':c.candidate_id,'title':c.title,'source':c.source,'source_uri':c.source_uri,'trust_class':c.trust_class,'language':c.language,'sha256':c.sha256,'staged_path':c.staged_path,'staged_at':c.staged_at,'state':c.state,'published_at':c.published_at,'rights_note':c.rights_note,'tags':list(c.tags),'rejection_reason':c.rejection_reason}
def main(argv:Optional[Sequence[str]]=None)->int:
    a=build_parser().parse_args(argv); l=Library(Path(a.root))
    try:
        common=lambda:{'title':a.title,'source':a.source,'source_uri':a.source_uri,'trust_class':a.trust,'language':a.language,'rights_note':a.rights_note,'tags':a.tag}
        if a.command=='stage': print(json.dumps(_cand(l.stage(a.file,**common())),indent=2,sort_keys=True)); return 0
        if a.command=='add': print(json.dumps(_item(l.add(a.file,published_at=a.published_at,**common())),indent=2,sort_keys=True)); return 0
        if a.command=='publish': print(json.dumps(_item(l.publish(a.candidate_id,published_at=a.published_at)),indent=2,sort_keys=True)); return 0
        if a.command=='reject': print(json.dumps(_cand(l.reject(a.candidate_id,a.reason)),indent=2,sort_keys=True)); return 0
        if a.command=='candidates':
            for c in l.list_candidates(a.state): print('%s\t%s\t%s\t%s'%(c.candidate_id,c.state,c.trust_class,c.title)); return 0
        if a.command=='inspect': print(json.dumps(_item(l.inspect(a.identifier)),indent=2,sort_keys=True)); return 0
        if a.command=='search':
            r=l.search(a.query,a.limit)
            for x in r: print('[%0.3f] %s (%s)\n  source=%s trust=%s sha256=%s\n  %s'%(x.score,x.title,x.item_id,x.source,x.trust_class,x.sha256,x.snippet))
            return 0 if r else 1
        if a.command=='verify':
            v=l.verify(a.identifier); print('valid' if v else 'checksum mismatch'); return 0 if v else 3
        if a.command=='remove': print(json.dumps(_item(l.remove(a.identifier)),indent=2,sort_keys=True)); return 0
        if a.command=='list':
            for i in l.list_items(): print('%s\t%s\t%s\t%s'%(i.item_id,i.trust_class,i.source,i.title)); return 0
    except (FileNotFoundError,ValueError,KeyError,RuntimeError) as e: print(str(e)); return 2
    return 2
if __name__=='__main__': raise SystemExit(main())
