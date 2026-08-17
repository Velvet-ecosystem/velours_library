"""SHA-bound source provenance sidecars for Velour library items."""
from __future__ import annotations
import argparse, hashlib, json, os, re, tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

_SCHEMA="velours_library.source_provenance.v1"
_SCOPE="velours_library_source_provenance_local_evidence"
_SHA=re.compile(r"^[0-9a-f]{64}$")
_FIELDS=("author","publisher","license_status","source_published_at","acquired_at","acquisition_method","source_library_imported_at")
_FORBIDDEN={"authority_granted","canonical_receipt","trust_class","capability","capabilities","permissions","commands","executor","court_decision"}

def _now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def _canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def _clean(v):
    if v is None:return None
    v=str(v).strip(); return v or None
def _time(v,field):
    v=_clean(v)
    if v is None:return None
    x=v[:-1]+"+00:00" if v.endswith("Z") else v
    try: datetime.fromisoformat(x) if ("T" in x or " " in x) else date.fromisoformat(x)
    except ValueError as exc: raise ValueError("%s must be an ISO-8601 date or datetime"%field) from exc
    return v

def validate_source_provenance_snapshot(value):
    if not isinstance(value,dict): raise ValueError("source_provenance must be an object")
    keys=set(value)
    bad=sorted(keys&_FORBIDDEN)
    if bad: raise ValueError("source_provenance contains authority field: %s"%bad[0])
    unknown=sorted(keys-set(_FIELDS))
    if unknown: raise ValueError("unknown source_provenance field: %s"%unknown[0])
    out={}
    for field in _FIELDS:
        raw=value.get(field)
        if raw is not None and not isinstance(raw,str): raise ValueError("source_provenance %s must be text or null"%field)
        out[field]=_clean(raw)
    for field in ("source_published_at","acquired_at","source_library_imported_at"): out[field]=_time(out[field],field)
    return out

@dataclass(frozen=True)
class SourceProvenance:
    schema:str; item_id:str; sha256:str; author:Optional[str]; publisher:Optional[str]; license_status:Optional[str]
    source_published_at:Optional[str]; acquired_at:Optional[str]; acquisition_method:Optional[str]; source_library_imported_at:Optional[str]
    recorded_at:str; origin_pack_id:Optional[str]=None; origin_adoption_id:Optional[str]=None; canonical_receipt:bool=False; authority_granted:bool=False
    def transferable(self): return {field:getattr(self,field) for field in _FIELDS}

class SourceProvenanceManager:
    def __init__(self,root,*,library=None,adoption=None,intake=None):
        self.root=Path(root); self.library=library; self.adoption=adoption; self.intake=intake
        self.catalog_dir=self.root/"catalog"/"source-provenance"; self.receipts_dir=self.root/"receipts"; self.events_path=self.receipts_dir/"source-provenance-events.jsonl"

    def set(self,item_id,*,author=None,publisher=None,license_status=None,source_published_at=None,acquired_at=None,acquisition_method=None,source_library_imported_at=None,origin_pack_id=None,origin_adoption_id=None,merge=True):
        item=self._library().inspect(item_id)
        if not _SHA.match(str(item.sha256)): raise RuntimeError("library item has invalid sha256: %s"%item_id)
        old=self.inspect_optional(item_id)
        data=validate_source_provenance_snapshot(dict(author=author,publisher=publisher,license_status=license_status,source_published_at=source_published_at,acquired_at=acquired_at,acquisition_method=acquisition_method,source_library_imported_at=source_library_imported_at))
        if merge and old:
            base=old.transferable(); base.update({k:v for k,v in data.items() if v is not None}); data=base
        if data["source_library_imported_at"] is None: data["source_library_imported_at"]=_clean(getattr(item,"imported_at",None))
        if not any(data.values()): raise ValueError("at least one source provenance field is required")
        recorded=old.recorded_at if old and old.transferable()==data else _now()
        rec=SourceProvenance(_SCHEMA,str(item.item_id),str(item.sha256),recorded_at=recorded,origin_pack_id=_clean(origin_pack_id) or (old.origin_pack_id if old else None),origin_adoption_id=_clean(origin_adoption_id) or (old.origin_adoption_id if old else None),**data)
        self._write(self._path(item_id),rec); self._event(rec); return rec

    def inspect(self,item_id):
        rec=self.inspect_optional(item_id)
        if rec is None: raise KeyError(item_id)
        return rec
    def inspect_optional(self,item_id,verify_binding=True):
        path=self._path(item_id)
        if not path.is_file(): return None
        rec=self._decode(json.loads(path.read_text()))
        if rec.item_id!=item_id: raise RuntimeError("source provenance item identity drift: %s"%item_id)
        if verify_binding and rec.sha256!=self._library().inspect(item_id).sha256: raise RuntimeError("source provenance payload binding drift: %s"%item_id)
        return rec
    def snapshot(self,item_id):
        rec=self.inspect_optional(item_id); return None if rec is None else rec.transferable()
    def list_records(self):
        if not self.catalog_dir.is_dir(): return []
        return [self._decode(json.loads(p.read_text())) for p in sorted(self.catalog_dir.glob("prov_*.json"))]

    def import_adoption(self,adoption_id):
        adoption=self._adoption().inspect(adoption_id)
        if adoption.get("schema")!="velours_library.pack_adoption.v1": raise ValueError("unsupported adoption record schema")
        if adoption.get("authority_granted") is not False: raise ValueError("provenance import refuses authority-bearing adoption records")
        cid=str(adoption.get("candidate_id") or "")
        if not cid: raise ValueError("adoption record missing candidate id")
        manifest=self._intake().verify_candidate(cid).get("manifest")
        if not isinstance(manifest,dict): raise RuntimeError("verified pack manifest unavailable")
        if manifest.get("pack_id")!=adoption.get("pack_id"): raise RuntimeError("adoption pack identity drift")
        members={str(x.get("item_id")):x for x in manifest.get("members",[]) if isinstance(x,dict) and x.get("item_id")}
        restored=[]
        for adopted in adoption.get("items",[]):
            if not isinstance(adopted,dict): continue
            remote=str(adopted.get("remote_item_id") or ""); local=str(adopted.get("local_item_id") or ""); member=members.get(remote)
            if not local or member is None or "source_provenance" not in member: continue
            if str(member.get("sha256") or "")!=str(adopted.get("sha256") or ""): raise RuntimeError("adoption/member payload identity drift: %s"%remote)
            if self._library().inspect(local).sha256!=member.get("sha256"): raise RuntimeError("local adopted payload identity drift: %s"%local)
            snap=validate_source_provenance_snapshot(member["source_provenance"])
            restored.append(self.set(local,origin_pack_id=str(adoption.get("pack_id") or "") or None,origin_adoption_id=str(adoption.get("adoption_id") or adoption_id),merge=False,**snap))
        return restored

    def _library(self):
        if self.library is None:
            from .catalog import Library
            self.library=Library(self.root)
        return self.library
    def _adoption(self):
        if self.adoption is None:
            from .pack_adoption import PackAdoptionManager
            self.adoption=PackAdoptionManager(self.root,library=self._library())
        return self.adoption
    def _intake(self):
        if self.intake is None:
            from .pack_intake import PackIntakeManager
            self.intake=PackIntakeManager(self.root)
        return self.intake
    def _path(self,item_id): return self.catalog_dir/("prov_%s.json"%hashlib.sha256(str(item_id).encode()).hexdigest()[:24])

    @staticmethod
    def _decode(raw):
        if raw.get("schema")!=_SCHEMA: raise ValueError("unsupported source provenance schema")
        iid=raw.get("item_id"); sha=raw.get("sha256")
        if not isinstance(iid,str) or not iid: raise ValueError("source provenance missing item id")
        if not isinstance(sha,str) or not _SHA.match(sha): raise ValueError("source provenance invalid sha256")
        if raw.get("canonical_receipt") is not False or raw.get("authority_granted") is not False: raise ValueError("source provenance cannot grant authority")
        recorded=raw.get("recorded_at")
        if not isinstance(recorded,str) or not recorded: raise ValueError("source provenance missing recorded_at")
        snap=validate_source_provenance_snapshot({f:raw.get(f) for f in _FIELDS})
        return SourceProvenance(_SCHEMA,iid,sha,recorded_at=recorded,origin_pack_id=_clean(raw.get("origin_pack_id")),origin_adoption_id=_clean(raw.get("origin_adoption_id")),**snap)

    def _write(self,path,rec):
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=".%s-"%path.name,dir=str(path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as h:
                json.dump(asdict(rec),h,sort_keys=True,separators=(",",":"),ensure_ascii=False); h.write("\n"); h.flush(); os.fsync(h.fileno())
            os.replace(tmp,str(path))
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
    def _event(self,rec):
        self.receipts_dir.mkdir(parents=True,exist_ok=True)
        seed=dict(action="set",item_id=rec.item_id,sha256=rec.sha256,source_provenance=rec.transferable(),origin_pack_id=rec.origin_pack_id,origin_adoption_id=rec.origin_adoption_id)
        eid="sprev_%s"%hashlib.sha256(_canon(seed)).hexdigest()[:24]
        if self.events_path.is_file():
            for line in self.events_path.read_text().splitlines():
                try:
                    if json.loads(line).get("event_id")==eid:return
                except ValueError: pass
        event=dict(event_id=eid,timestamp=_now(),action="set",canonical_receipt=False,receipt_scope=_SCOPE,details=dict(seed,authority_granted=False))
        with self.events_path.open("a",encoding="utf-8") as h: h.write(json.dumps(event,sort_keys=True)+"\n")

def _parser():
    p=argparse.ArgumentParser(description="Manage Velour source provenance sidecars"); p.add_argument("--root",required=True); sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("set"); s.add_argument("item_id")
    for flag in ("author","publisher","license-status","acquired-at","acquisition-method"): s.add_argument("--"+flag)
    s.add_argument("--published-at",dest="source_published_at")
    i=sub.add_parser("inspect"); i.add_argument("item_id"); a=sub.add_parser("import-adoption"); a.add_argument("adoption_id"); sub.add_parser("list"); return p

def main(argv=None):
    args=_parser().parse_args(argv); m=SourceProvenanceManager(args.root)
    try:
        if args.command=="set": out=asdict(m.set(args.item_id,author=args.author,publisher=args.publisher,license_status=args.license_status,source_published_at=args.source_published_at,acquired_at=args.acquired_at,acquisition_method=args.acquisition_method))
        elif args.command=="inspect": out=asdict(m.inspect(args.item_id))
        elif args.command=="import-adoption": out=[asdict(x) for x in m.import_adoption(args.adoption_id)]
        else: out=[asdict(x) for x in m.list_records()]
        print(json.dumps(out,indent=2,sort_keys=True)); return 0
    except (FileNotFoundError,KeyError,RuntimeError,ValueError) as exc: print(str(exc)); return 2
if __name__=="__main__": raise SystemExit(main())
