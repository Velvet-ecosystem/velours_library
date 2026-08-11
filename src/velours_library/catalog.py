"""Core archive, catalog, provenance, quarantine, search, and verification for Velour's Library."""
from __future__ import annotations

import hashlib, json, mimetypes, re, shutil, sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

_TEXT_EXTENSIONS = {'.txt','.md','.rst','.csv','.json','.yaml','.yml','.toml','.ini','.log'}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_TRUST_CLASSES = {'primary','scholarly','secondary','community','owner','generated','unknown'}

@dataclass(frozen=True)
class LibraryItem:
    item_id: str; title: str; source: str; source_uri: Optional[str]; trust_class: str
    media_type: str; language: str; sha256: str; storage_path: str
    extracted_text_path: Optional[str]; imported_at: str; published_at: Optional[str]
    rights_note: Optional[str]; tags: Tuple[str,...]

@dataclass(frozen=True)
class SearchResult:
    item_id: str; title: str; source: str; trust_class: str; sha256: str; score: float; snippet: str

@dataclass(frozen=True)
class Candidate:
    candidate_id: str; title: str; source: str; source_uri: Optional[str]; trust_class: str
    language: str; sha256: str; staged_path: str; staged_at: str; state: str
    published_at: Optional[str]; rights_note: Optional[str]; tags: Tuple[str,...]; rejection_reason: Optional[str]

class Library:
    """A shared, model-independent offline library for the Velvet ecosystem."""
    def __init__(self, root: Union[str,Path], *, max_file_bytes: int=256*1024*1024,
                 max_extract_bytes: int=16*1024*1024, max_pdf_bytes: int=64*1024*1024) -> None:
        self.root=Path(root); self.catalog_dir=self.root/'catalog'; self.incoming_dir=self.root/'incoming'
        self.archive_dir=self.root/'archive'/'sha256'; self.text_dir=self.root/'indexes'/'text'; self.receipts_dir=self.root/'receipts'
        self.db_path=self.catalog_dir/'library.sqlite3'; self.receipt_path=self.receipts_dir/'library-events.jsonl'
        self.max_file_bytes=max_file_bytes; self.max_extract_bytes=max_extract_bytes; self.max_pdf_bytes=max_pdf_bytes; self._fts5=False
        self._prepare()

    def _prepare(self)->None:
        for p in (self.catalog_dir,self.incoming_dir,self.archive_dir,self.text_dir,self.receipts_dir): p.mkdir(parents=True,exist_ok=True)
        with self._connect() as c:
            c.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS items(item_id TEXT PRIMARY KEY,title TEXT NOT NULL,source TEXT NOT NULL,source_uri TEXT,trust_class TEXT NOT NULL,media_type TEXT NOT NULL,language TEXT NOT NULL,sha256 TEXT NOT NULL,storage_path TEXT NOT NULL,extracted_text_path TEXT,imported_at TEXT NOT NULL,published_at TEXT,rights_note TEXT);
            CREATE INDEX IF NOT EXISTS idx_items_sha256 ON items(sha256);
            CREATE TABLE IF NOT EXISTS tags(item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,tag TEXT NOT NULL,PRIMARY KEY(item_id,tag));
            CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY,title TEXT NOT NULL,source TEXT NOT NULL,source_uri TEXT,trust_class TEXT NOT NULL,language TEXT NOT NULL,sha256 TEXT NOT NULL,staged_path TEXT NOT NULL,staged_at TEXT NOT NULL,state TEXT NOT NULL,published_at TEXT,rights_note TEXT,tags_json TEXT NOT NULL,rejection_reason TEXT);
            CREATE INDEX IF NOT EXISTS idx_candidates_sha256 ON candidates(sha256);
            ''')
            try:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS item_fts USING fts5(item_id UNINDEXED,title,source,tags,body)")
                self._fts5=True
            except sqlite3.OperationalError: self._fts5=False

    def _connect(self):
        c=sqlite3.connect(str(self.db_path)); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

    def stage(self, source_file: Union[str,Path], *, title: str, source: str, source_uri: Optional[str]=None,
              trust_class: str='unknown', language: str='en', rights_note: Optional[str]=None,
              tags: Iterable[str]=()) -> Candidate:
        src=Path(source_file)
        if not src.is_file(): raise FileNotFoundError(str(src))
        if not title.strip() or not source.strip(): raise ValueError('title and source are required')
        size=src.stat().st_size
        if size>self.max_file_bytes: raise ValueError('source exceeds max_file_bytes')
        trust_class=(trust_class.strip().lower() or 'unknown')
        if trust_class not in _TRUST_CLASSES: raise ValueError('unknown trust class: %s'%trust_class)
        sha=self._sha256(src); cid='cand_%s'%uuid4().hex; staged=self.incoming_dir/(cid + src.suffix.lower())
        shutil.copy2(str(src),str(staged)); clean_tags=tuple(sorted({str(t).strip() for t in tags if str(t).strip()})); now=self._utc_now()
        with self._connect() as c:
            c.execute('''INSERT INTO candidates(candidate_id,title,source,source_uri,trust_class,language,sha256,staged_path,staged_at,state,published_at,rights_note,tags_json,rejection_reason) VALUES(?,?,?,?,?,?,?,?,?,'staged',NULL,?,?,NULL)''',
                      (cid,title.strip(),source.strip(),source_uri.strip() if source_uri else None,trust_class,language.strip() or 'en',sha,str(staged),now,rights_note,json.dumps(clean_tags)))
        cand=self.inspect_candidate(cid); self._write_candidate_event('stage',cand,{'source_file':str(src.resolve()),'bytes':size}); return cand

    def publish(self, candidate_id: str, *, published_at: Optional[str]=None) -> LibraryItem:
        cand=self.inspect_candidate(candidate_id)
        if cand.state!='staged': raise ValueError('candidate is not staged')
        staged=Path(cand.staged_path)
        if not staged.is_file(): raise RuntimeError('staged payload missing')
        if self._sha256(staged)!=cand.sha256: raise RuntimeError('staged payload checksum mismatch')
        storage=self.archive_dir/cand.sha256[:2]/cand.sha256; storage.parent.mkdir(parents=True,exist_ok=True)
        if not storage.exists(): shutil.copy2(str(staged),str(storage))
        elif self._sha256(storage)!=cand.sha256: raise RuntimeError('archive hash collision or corrupted canonical object')
        iid='lib_%s'%uuid4().hex; extracted=self._extract_text(staged,iid); media=mimetypes.guess_type(cand.title)[0] or 'application/octet-stream'; now=self._utc_now(); pub=published_at
        with self._connect() as c:
            c.execute('''INSERT INTO items(item_id,title,source,source_uri,trust_class,media_type,language,sha256,storage_path,extracted_text_path,imported_at,published_at,rights_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (iid,cand.title,cand.source,cand.source_uri,cand.trust_class,media,cand.language,cand.sha256,str(storage),str(extracted) if extracted else None,now,pub,cand.rights_note))
            c.executemany('INSERT INTO tags(item_id,tag) VALUES(?,?)',[(iid,t) for t in cand.tags])
            if self._fts5:
                body=extracted.read_text(encoding='utf-8',errors='replace') if extracted else ''
                c.execute('INSERT INTO item_fts(item_id,title,source,tags,body) VALUES(?,?,?,?,?)',(iid,cand.title,cand.source,' '.join(cand.tags),body))
            c.execute("UPDATE candidates SET state='published',published_at=? WHERE candidate_id=?",(now,cand.candidate_id))
        staged.unlink(missing_ok=True); item=self.inspect(iid); self._write_event('publish',item,{'candidate_id':cand.candidate_id}); return item

    def reject(self,candidate_id:str,reason:str)->Candidate:
        cand=self.inspect_candidate(candidate_id)
        if cand.state!='staged': raise ValueError('candidate is not staged')
        Path(cand.staged_path).unlink(missing_ok=True)
        with self._connect() as c: c.execute("UPDATE candidates SET state='rejected',rejection_reason=? WHERE candidate_id=?",(reason.strip() or 'rejected',cand.candidate_id))
        updated=self.inspect_candidate(cand.candidate_id); self._write_candidate_event('reject',updated,{'reason':updated.rejection_reason}); return updated

    def add(self, source_file: Union[str,Path], **kwargs) -> LibraryItem:
        published_at=kwargs.pop('published_at',None); cand=self.stage(source_file,**kwargs); return self.publish(cand.candidate_id,published_at=published_at)

    def inspect_candidate(self,identifier:str)->Candidate:
        with self._connect() as c:
            rows=c.execute('SELECT * FROM candidates WHERE candidate_id=? OR candidate_id LIKE ? OR sha256=? OR sha256 LIKE ? ORDER BY candidate_id',(identifier,identifier+'%',identifier,identifier+'%')).fetchall()
        if not rows: raise KeyError(identifier)
        exact=[r for r in rows if r['candidate_id']==identifier or r['sha256']==identifier]
        row=exact[0] if exact else rows[0] if len(rows)==1 else None
        if row is None: raise KeyError('ambiguous identifier: %s'%identifier)
        return self._row_to_candidate(row)

    def list_candidates(self,state:Optional[str]=None)->List[Candidate]:
        with self._connect() as c:
            rows=c.execute('SELECT * FROM candidates'+(' WHERE state=?' if state else '')+' ORDER BY staged_at,candidate_id',((state,) if state else ())).fetchall()
        return [self._row_to_candidate(r) for r in rows]

    def inspect(self,identifier:str)->LibraryItem:
        with self._connect() as c:
            rows=c.execute('SELECT * FROM items WHERE item_id=? OR item_id LIKE ? OR sha256=? OR sha256 LIKE ? ORDER BY item_id',(identifier,identifier+'%',identifier,identifier+'%')).fetchall()
            if not rows: raise KeyError(identifier)
            exact=[r for r in rows if r['item_id']==identifier or r['sha256']==identifier]; row=exact[0] if exact else rows[0] if len(rows)==1 else None
            if row is None: raise KeyError('ambiguous identifier: %s'%identifier)
            tags=tuple(r[0] for r in c.execute('SELECT tag FROM tags WHERE item_id=? ORDER BY tag',(row['item_id'],)))
        return self._row_to_item(row,tags)

    def list_items(self)->List[LibraryItem]:
        with self._connect() as c:
            rows=c.execute('SELECT * FROM items ORDER BY imported_at,item_id').fetchall(); out=[]
            for r in rows:
                tags=tuple(x[0] for x in c.execute('SELECT tag FROM tags WHERE item_id=? ORDER BY tag',(r['item_id'],))); out.append(self._row_to_item(r,tags))
            return out

    def search(self,query:str,limit:int=10)->List[SearchResult]:
        terms=[t.lower() for t in _TOKEN_RE.findall(query)]
        if not terms or limit<=0:return []
        if self._fts5:
            try:return self._search_fts(terms,limit)
            except sqlite3.OperationalError:pass
        return self._search_fallback(terms,limit)

    def _search_fts(self,terms:Sequence[str],limit:int)->List[SearchResult]:
        match=' AND '.join('"%s"'%t.replace('"','""') for t in terms)
        with self._connect() as c:
            rows=c.execute('''SELECT f.item_id,f.title,f.source,i.trust_class,i.sha256,bm25(item_fts,0.0,5.0,4.0,3.0,1.0) rank,snippet(item_fts,4,'','',' … ',24) snippet FROM item_fts f JOIN items i ON i.item_id=f.item_id WHERE item_fts MATCH ? ORDER BY rank ASC,f.title COLLATE NOCASE ASC,f.item_id ASC LIMIT ?''',(match,limit)).fetchall()
        return [SearchResult(r['item_id'],r['title'],r['source'],r['trust_class'],r['sha256'],float(-r['rank']),' '.join((r['snippet'] or '').split())) for r in rows]

    def _search_fallback(self,terms:Sequence[str],limit:int)->List[SearchResult]:
        out=[]
        for i in self.list_items():
            meta=' '.join((i.title,i.source,i.trust_class,' '.join(i.tags))).lower(); body=''
            if i.extracted_text_path and Path(i.extracted_text_path).is_file(): body=Path(i.extracted_text_path).read_text(encoding='utf-8',errors='replace').lower()
            score=float(sum(meta.count(t)*5+body.count(t) for t in terms))
            if score>0: out.append(SearchResult(i.item_id,i.title,i.source,i.trust_class,i.sha256,score,self._snippet(body or meta,terms)))
        out.sort(key=lambda r:(-r.score,r.title.lower(),r.item_id)); return out[:limit]

    def verify(self,identifier:str)->bool:
        i=self.inspect(identifier); p=Path(i.storage_path); valid=p.is_file() and self._sha256(p)==i.sha256; self._write_event('verify',i,{'valid':valid}); return valid

    def remove(self,identifier:str)->LibraryItem:
        i=self.inspect(identifier)
        with self._connect() as c:
            if self._fts5:c.execute('DELETE FROM item_fts WHERE item_id=?',(i.item_id,))
            c.execute('DELETE FROM items WHERE item_id=?',(i.item_id,)); remaining=c.execute('SELECT COUNT(*) FROM items WHERE sha256=?',(i.sha256,)).fetchone()[0]
        if i.extracted_text_path: Path(i.extracted_text_path).unlink(missing_ok=True)
        if remaining==0: Path(i.storage_path).unlink(missing_ok=True)
        self._write_event('remove',i,{'canonical_payload_removed':remaining==0}); return i

    def _extract_text(self,source:Path,item_id:str)->Optional[Path]:
        size=source.stat().st_size; suffix=self._detect_suffix(source)
        if size>self.max_extract_bytes and suffix!='.pdf': return None
        text=None
        if suffix in _TEXT_EXTENSIONS: text=source.read_text(encoding='utf-8',errors='replace')
        elif suffix=='.pdf':
            if size>self.max_pdf_bytes:return None
            text=self._extract_pdf(source)
        if text is None:return None
        dest=self.text_dir/(item_id+'.txt'); dest.write_text(text,encoding='utf-8'); return dest

    @staticmethod
    def _detect_suffix(source:Path)->str:
        try:
            with source.open('rb') as h: head=h.read(5)
        except OSError:return source.suffix.lower()
        if head==b'%PDF-':return '.pdf'
        return source.suffix.lower()

    @staticmethod
    def _extract_pdf(source:Path)->Optional[str]:
        try: from pypdf import PdfReader  # type: ignore
        except ImportError:return None
        reader=PdfReader(str(source)); return '\n\n'.join((p.extract_text() or '') for p in reader.pages)

    def _write_event(self,action:str,item:LibraryItem,details:Optional[dict]=None)->None:
        self._append_event({'event_id':'lev_%s'%uuid4().hex,'timestamp':self._utc_now(),'action':action,'item_id':item.item_id,'sha256':item.sha256,'canonical_receipt':False,'receipt_scope':'velours_library_local_evidence','details':details or {}})
    def _write_candidate_event(self,action:str,c:Candidate,details:Optional[dict]=None)->None:
        self._append_event({'event_id':'lev_%s'%uuid4().hex,'timestamp':self._utc_now(),'action':action,'candidate_id':c.candidate_id,'sha256':c.sha256,'canonical_receipt':False,'receipt_scope':'velours_library_local_evidence','details':details or {}})
    def _append_event(self,event:dict)->None:
        with self.receipt_path.open('a',encoding='utf-8') as h:h.write(json.dumps(event,sort_keys=True)+'\n')

    @staticmethod
    def _row_to_item(r,tags): return LibraryItem(r['item_id'],r['title'],r['source'],r['source_uri'],r['trust_class'],r['media_type'],r['language'],r['sha256'],r['storage_path'],r['extracted_text_path'],r['imported_at'],r['published_at'],r['rights_note'],tags)
    @staticmethod
    def _row_to_candidate(r): return Candidate(r['candidate_id'],r['title'],r['source'],r['source_uri'],r['trust_class'],r['language'],r['sha256'],r['staged_path'],r['staged_at'],r['state'],r['published_at'],r['rights_note'],tuple(json.loads(r['tags_json'])),r['rejection_reason'])
    @staticmethod
    def _sha256(path:Path)->str:
        d=hashlib.sha256()
        with path.open('rb') as h:
            for chunk in iter(lambda:h.read(1024*1024),b''):d.update(chunk)
        return d.hexdigest()
    @staticmethod
    def _utc_now()->str:return datetime.now(timezone.utc).isoformat()
    @staticmethod
    def _snippet(text:str,terms:Sequence[str],width:int=220)->str:
        pos=[text.find(t) for t in terms if t in text]; first=min(pos) if pos else 0; start=max(0,first-width//3); return ' '.join(text[start:start+width].split())
