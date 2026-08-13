import hashlib
import json
import os
from pathlib import Path

import pytest

from velours_library.pack_intake import PackIntakeManager
from velours_library.packs import KnowledgePackManager


def make_bundle(root: Path, payloads=(b'alpha manual',), extra=False):
    root.mkdir(parents=True)
    members=[]
    for n, data in enumerate(payloads):
        sha=hashlib.sha256(data).hexdigest(); p=root/'objects'/'sha256'/sha[:2]/sha; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
        members.append({'item_id':'source_%d'%n,'title':'Item %d'%n,'source':'Maker','sha256':sha})
    seed={'schema':'velours_library.knowledge_pack.v1','name':'Workshop','version':'1','description':None,'members':members}
    manifest=dict(seed); manifest['pack_id']=KnowledgePackManager.verify_manifest(seed)['expected_pack_id']; (root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,separators=(',',':'))+'\n')
    if extra: (root/'ignore-me.txt').write_text('not canonical')
    return manifest


def test_stage_reconstructs_only_canonical_bundle(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src,extra=True); mgr=PackIntakeManager(tmp_path/'lib')
    c=mgr.stage(src,source_label='garage node'); staged=Path(c.staged_path)
    assert c.state=='verified' and (staged/'manifest.json').is_file() and not (staged/'ignore-me.txt').exists()
    assert KnowledgePackManager.verify_export(staged)['valid']


def test_stage_rejects_tampered_payload(tmp_path):
    src=tmp_path/'bundle'; m=make_bundle(src); sha=m['members'][0]['sha256']; (src/'objects'/'sha256'/sha[:2]/sha).write_bytes(b'tampered')
    with pytest.raises(ValueError): PackIntakeManager(tmp_path/'lib').stage(src,source_label='usb')


def test_stage_caps_member_count(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src,payloads=(b'a',b'b'))
    with pytest.raises(ValueError): PackIntakeManager(tmp_path/'lib',max_members=1).stage(src,source_label='usb')


def test_stage_caps_total_payload_bytes_before_adoption(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src,payloads=(b'12345',))
    with pytest.raises(ValueError): PackIntakeManager(tmp_path/'lib',max_pack_bytes=4).stage(src,source_label='usb')


def test_approve_reverifies_staged_bytes(tmp_path):
    src=tmp_path/'bundle'; m=make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb'); sha=m['members'][0]['sha256']; p=Path(c.staged_path)/'objects'/'sha256'/sha[:2]/sha; p.write_bytes(b'changed')
    with pytest.raises(RuntimeError): mgr.approve(c.candidate_id)


def test_approve_is_not_install_or_authority_grant(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb'); approved=mgr.approve(c.candidate_id)
    assert approved.state=='approved' and Path(approved.staged_path).exists()
    events=[json.loads(x) for x in mgr.events_path.read_text().splitlines()]
    assert events[-1]['details']=={'authority_granted':False,'installed':False} and events[-1]['canonical_receipt'] is False


def test_reject_removes_payload_but_keeps_audit_metadata(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb'); rejected=mgr.reject(c.candidate_id,'wrong cartridge')
    assert rejected.state=='rejected' and rejected.rejection_reason=='wrong cartridge' and not Path(c.staged_path).exists()
    assert mgr.inspect(c.candidate_id).state=='rejected'


def test_symlink_payload_is_refused(tmp_path):
    src=tmp_path/'bundle'; m=make_bundle(src); sha=m['members'][0]['sha256']; p=src/'objects'/'sha256'/sha[:2]/sha; outside=tmp_path/'outside'; outside.write_bytes(p.read_bytes()); p.unlink()
    try: os.symlink(str(outside), str(p))
    except (OSError, NotImplementedError): pytest.skip('symlink unavailable')
    with pytest.raises(ValueError): PackIntakeManager(tmp_path/'lib').stage(src,source_label='usb')


def test_cli_stage_and_list(tmp_path, capsys):
    from velours_library.pack_intake import main
    src=tmp_path/'bundle'; make_bundle(src); root=tmp_path/'lib'
    assert main(['--root',str(root),'stage',str(src),'--source-label','usb'])==0
    stage_output=capsys.readouterr().out; assert '"state": "verified"' in stage_output
    assert main(['--root',str(root),'list','--state','verified'])==0
    assert 'verified' in capsys.readouterr().out


def test_approved_candidate_cannot_be_rejected_without_separate_lifecycle(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb'); mgr.approve(c.candidate_id)
    with pytest.raises(ValueError): mgr.reject(c.candidate_id,'changed my mind')


def test_duplicate_verified_pack_is_refused(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib')
    first=mgr.stage(src,source_label='usb-a')
    with pytest.raises(ValueError, match='already present'):
        mgr.stage(src,source_label='usb-b')
    assert mgr.inspect(first.candidate_id).state=='verified'


def test_approved_candidate_cannot_be_approved_twice(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb'); mgr.approve(c.candidate_id)
    with pytest.raises(ValueError): mgr.approve(c.candidate_id)


def test_symlinked_intermediate_objects_directory_is_refused(tmp_path):
    src=tmp_path/'bundle'; manifest=make_bundle(src); sha=manifest['members'][0]['sha256']
    outside=tmp_path/'outside-objects'; target=outside/'sha256'/sha[:2]/sha; target.parent.mkdir(parents=True); target.write_bytes(b'alpha manual')
    shutil_target=src/'objects';
    import shutil
    shutil.rmtree(shutil_target)
    try: os.symlink(str(outside), str(shutil_target), target_is_directory=True)
    except (OSError, NotImplementedError): pytest.skip('symlink unavailable')
    with pytest.raises(ValueError): PackIntakeManager(tmp_path/'lib').stage(src,source_label='usb')


def test_verify_candidate_is_read_only_and_accepts_approved(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb')
    before=mgr.inspect(c.candidate_id); checked=mgr.verify_candidate(c.candidate_id)
    assert checked['valid'] is True and checked['manifest']['pack_id']==c.pack_id and mgr.inspect(c.candidate_id)==before
    approved=mgr.approve(c.candidate_id); assert mgr.verify_candidate(approved.candidate_id)['valid'] is True


def test_verify_candidate_rejects_changed_manifest(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb')
    p=Path(c.staged_path)/'manifest.json'; raw=json.loads(p.read_text()); raw['name']='Changed'; p.write_text(json.dumps(raw))
    with pytest.raises(RuntimeError): mgr.verify_candidate(c.candidate_id)


def test_verify_candidate_rejects_tampered_staged_path_metadata(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb')
    meta=mgr.catalog_dir/(c.candidate_id+'.json'); raw=json.loads(meta.read_text()); raw['staged_path']=str(src); meta.write_text(json.dumps(raw))
    with pytest.raises(RuntimeError, match='staged path changed'):
        mgr.verify_candidate(c.candidate_id)


def test_verify_candidate_rejects_tampered_name_or_size_metadata(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); c=mgr.stage(src,source_label='usb')
    meta=mgr.catalog_dir/(c.candidate_id+'.json'); raw=json.loads(meta.read_text()); raw['name']='Other'; meta.write_text(json.dumps(raw))
    with pytest.raises(RuntimeError, match='metadata changed'):
        mgr.verify_candidate(c.candidate_id)
    raw=json.loads(meta.read_text()); raw['name']=c.name; raw['payload_bytes']=raw['payload_bytes']+1; meta.write_text(json.dumps(raw))
    with pytest.raises(RuntimeError, match='size metadata changed'):
        mgr.verify_candidate(c.candidate_id)


def test_rejected_pack_can_be_staged_again_as_new_candidate(tmp_path):
    src=tmp_path/'bundle'; make_bundle(src); mgr=PackIntakeManager(tmp_path/'lib'); first=mgr.stage(src,source_label='usb'); mgr.reject(first.candidate_id,'retry later'); second=mgr.stage(src,source_label='usb')
    assert first.candidate_id!=second.candidate_id and second.state=='verified'
