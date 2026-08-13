import json
from dataclasses import dataclass
import pytest
from velours_library.pack_lifecycle import PackLifecycleManager

@dataclass
class Item:
    item_id: str; sha256: str; trust_class: str; tags: tuple
class Library:
    def __init__(self): self.items = {}
    def inspect(self, key):
        if key not in self.items: raise KeyError(key)
        return self.items[key]
    def verify(self, key): return key in self.items
class Adoption:
    def __init__(self): self.records = {}
    def inspect(self, key):
        exact = [v for k,v in self.records.items() if k == key]
        if exact: return exact[0]
        rows = [v for k,v in self.records.items() if k.startswith(key)]
        if len(rows) == 1: return rows[0]
        raise KeyError(key)

def record(aid, name="Workshop", version="1.0", char="a"):
    pid = "kpack_" + char*24; iid = "lib_" + aid[-8:]
    tag = "velour-adoption:%s:%s:remote-1" % (aid,pid)
    return {"schema":"velours_library.pack_adoption.v1","adoption_id":aid,"candidate_id":"pcand_x",
        "pack_id":pid,"pack_name":name,"pack_version":version,"source_label":"garage",
        "manifest_sha256":("f" if char != "f" else "e")*64,"local_trust":"unknown",
        "canonical_receipt":False,"authority_granted":False,
        "items":[{"local_item_id":iid,"local_candidate_id":"cand_x","local_trust_class":"unknown",
        "adoption_tag":tag,"remote_item_id":"r1","title":"Manual","source":"maker","sha256":char*64}]}
def add(env, rec):
    m,a,l=env; a.records[rec["adoption_id"]]=rec; raw=rec["items"][0]
    l.items[raw["local_item_id"]]=Item(raw["local_item_id"],raw["sha256"],rec["local_trust"],(raw["adoption_tag"],))
    return rec
@pytest.fixture
def env(tmp_path):
    a,l=Adoption(),Library(); return PackLifecycleManager(tmp_path,adoption=a,library=l),a,l
def pair(env):
    old=add(env,record("adopt_old00001",char="a")); new=add(env,record("adopt_new00002",version="2",char="b"))
    env[0].register(old["adoption_id"]); env[0].register(new["adoption_id"]); return old,new

def test_01_casefold_family(env):
    a=add(env,record("adopt_case0001",name="Workshop",char="a")); b=add(env,record("adopt_case0002",name=" workshop ",version="2",char="b"))
    assert env[0].register(a["adoption_id"])["family_id"] == env[0].register(b["adoption_id"])["family_id"]
def test_02_register_installed(env):
    r=add(env,record("adopt_reg00001")); assert env[0].register(r["adoption_id"])["state"]=="installed"
def test_03_register_idempotent(env):
    r=add(env,record("adopt_reg00002")); x=env[0].register(r["adoption_id"]); y=env[0].register(r["adoption_id"]); assert x["registered_at"]==y["registered_at"] and len(env[0].history("Workshop"))==1
def test_04_register_missing(env):
    with pytest.raises(KeyError): env[0].register("missing")
def test_05_boundary_drift(env):
    r=record("adopt_boundary"); r["authority_granted"]=True; add(env,r)
    with pytest.raises(ValueError): env[0].register(r["adoption_id"])
def test_06_hash_drift(env):
    r=add(env,record("adopt_hashdrf")); env[2].items[r["items"][0]["local_item_id"]].sha256="c"*64
    with pytest.raises(RuntimeError): env[0].register(r["adoption_id"])
def test_07_activate(env):
    r=add(env,record("adopt_active01")); env[0].register(r["adoption_id"]); assert env[0].activate(r["adoption_id"])["state"]=="active"
def test_08_activate_idempotent(env):
    r=add(env,record("adopt_active02")); env[0].register(r["adoption_id"]); x=env[0].activate(r["adoption_id"]); y=env[0].activate(r["adoption_id"]); assert x["activated_at"]==y["activated_at"]
def test_09_second_active_refused(env):
    old,new=pair(env); env[0].activate(old["adoption_id"])
    with pytest.raises(ValueError): env[0].activate(new["adoption_id"])
def test_10_stale_installed(env):
    r=add(env,record("adopt_stale001")); env[0].register(r["adoption_id"]); assert env[0].mark_stale(r["adoption_id"])["state"]=="stale"
def test_11_stale_active_clears_current(env):
    r=add(env,record("adopt_stale002")); env[0].register(r["adoption_id"]); env[0].activate(r["adoption_id"]); env[0].mark_stale(r["adoption_id"]); assert env[0].current("Workshop") is None
def test_12_stale_idempotent(env):
    r=add(env,record("adopt_stale003")); env[0].register(r["adoption_id"]); x=env[0].mark_stale(r["adoption_id"]); y=env[0].mark_stale(r["adoption_id"]); assert x["stale_at"]==y["stale_at"]
def test_13_supersede(env):
    old,new=pair(env); env[0].activate(old["adoption_id"]); env[0].supersede(old["adoption_id"],new["adoption_id"]); h={x["adoption_id"]:x for x in env[0].history("Workshop")}; assert h[old["adoption_id"]]["state"]=="superseded" and env[0].current("Workshop")["adoption_id"]==new["adoption_id"]
def test_14_successor_must_be_registered(env):
    old=add(env,record("adopt_oldreg01",char="a")); new=add(env,record("adopt_newreg02",version="2",char="b")); env[0].register(old["adoption_id"]); env[0].activate(old["adoption_id"])
    with pytest.raises(KeyError): env[0].supersede(old["adoption_id"],new["adoption_id"])
def test_15_same_family_required(env):
    old=add(env,record("adopt_fam0001",name="Workshop",char="a")); new=add(env,record("adopt_fam0002",name="Electronics",version="2",char="b")); env[0].register(old["adoption_id"]); env[0].register(new["adoption_id"]); env[0].activate(old["adoption_id"])
    with pytest.raises(ValueError): env[0].supersede(old["adoption_id"],new["adoption_id"])
def test_16_predecessor_must_be_active(env):
    old,new=pair(env)
    with pytest.raises(ValueError): env[0].supersede(old["adoption_id"],new["adoption_id"])
def test_17_remove_logical(env):
    r=add(env,record("adopt_remove01")); env[0].register(r["adoption_id"]); iid=r["items"][0]["local_item_id"]; assert env[0].remove(r["adoption_id"])["state"]=="removed" and iid in env[2].items
def test_18_remove_active_refused(env):
    r=add(env,record("adopt_remove02")); env[0].register(r["adoption_id"]); env[0].activate(r["adoption_id"])
    with pytest.raises(ValueError): env[0].remove(r["adoption_id"])
def test_19_current_casefold(env):
    r=add(env,record("adopt_curr0001")); env[0].register(r["adoption_id"]); env[0].activate(r["adoption_id"]); assert env[0].current(" WORKSHOP ")["adoption_id"]==r["adoption_id"]
def test_20_binding_drift(env):
    r=add(env,record("adopt_verify01")); s=env[0].register(r["adoption_id"]); p=env[0]._path("Workshop"); f=json.loads(p.read_text()); f["revisions"][0]["manifest_sha256"]="0"*64; p.write_text(json.dumps(f))
    with pytest.raises(RuntimeError): env[0].verify(r["adoption_id"])
def test_21_event_repair(env,monkeypatch):
    r=add(env,record("adopt_event001")); env[0].register(r["adoption_id"]); real=env[0]._event; n={"x":0}
    def flaky(*a,**k): n["x"]+=1; (_ for _ in ()).throw(OSError("disk")) if n["x"]==1 else None; return real(*a,**k)
    monkeypatch.setattr(env[0],"_event",flaky)
    with pytest.raises(OSError): env[0].activate(r["adoption_id"])
    env[0].activate(r["adoption_id"]); assert env[0].events_path.read_text().count('"action": "activate"')==1
def test_22_atomic_failure_preserves_old(env,monkeypatch):
    old,new=pair(env); env[0].activate(old["adoption_id"]); real=__import__("os").replace
    def fail(src,dst):
        if str(dst).endswith(".json"): raise OSError("replace")
        return real(src,dst)
    monkeypatch.setattr("velours_library.pack_lifecycle.os.replace",fail)
    with pytest.raises(OSError): env[0].supersede(old["adoption_id"],new["adoption_id"])
    assert env[0].current("Workshop")["adoption_id"]==old["adoption_id"]
