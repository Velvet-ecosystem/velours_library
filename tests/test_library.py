import json
from pathlib import Path
import pytest
from velours_library import Library

def test_add_search_inspect_and_verify(tmp_path:Path):
    s=tmp_path/'n.md'; s.write_text('# Alternator\nInspect pulley alignment.',encoding='utf-8'); l=Library(tmp_path/'lib'); i=l.add(s,title='Alternator Notes',source='owner',trust_class='owner',tags=['repair']); assert l.inspect(i.item_id).title=='Alternator Notes'; assert l.verify(i.item_id); assert l.search('pulley')[0].item_id==i.item_id

def test_duplicate_bytes_keep_separate_provenance(tmp_path:Path):
    s=tmp_path/'same.txt'; s.write_text('shared bytes'); l=Library(tmp_path/'lib'); a=l.add(s,title='A',source='a'); b=l.add(s,title='B',source='b'); assert a.sha256==b.sha256 and a.item_id!=b.item_id and a.storage_path==b.storage_path

def test_search_returns_source_and_trust(tmp_path:Path):
    s=tmp_path/'m.txt'; s.write_text('battery charging voltage'); l=Library(tmp_path/'lib'); i=l.add(s,title='Battery',source='Maker',trust_class='primary'); r=l.search('battery')[0]; assert (r.source,r.trust_class)==('Maker','primary')

def test_verify_detects_tampering(tmp_path:Path):
    s=tmp_path/'g.txt'; s.write_text('original'); l=Library(tmp_path/'lib'); i=l.add(s,title='G',source='local'); Path(i.storage_path).write_text('changed'); assert not l.verify(i.item_id)

def test_remove_preserves_shared_payload_until_last_reference(tmp_path:Path):
    s=tmp_path/'same.txt'; s.write_text('shared'); l=Library(tmp_path/'lib'); a=l.add(s,title='A',source='a'); b=l.add(s,title='B',source='b'); p=Path(a.storage_path); l.remove(a.item_id); assert p.exists(); l.remove(b.item_id); assert not p.exists()

def test_inspect_accepts_unique_sha_prefix(tmp_path:Path):
    s=tmp_path/'x.txt'; s.write_text('unique'); l=Library(tmp_path/'lib'); i=l.add(s,title='X',source='local'); assert l.inspect(i.sha256[:12]).item_id==i.item_id

def test_library_events_are_noncanonical(tmp_path:Path):
    s=tmp_path/'x.txt'; s.write_text('evidence'); l=Library(tmp_path/'lib'); i=l.add(s,title='X',source='local'); l.verify(i.item_id); ev=[json.loads(x) for x in l.receipt_path.read_text().splitlines()]; assert ev and all(e['canonical_receipt'] is False for e in ev)

def test_staged_candidate_is_not_searchable_until_publish(tmp_path:Path):
    s=tmp_path/'secret.txt'; s.write_text('quarantine telescope'); l=Library(tmp_path/'lib'); c=l.stage(s,title='Staged',source='local'); assert l.search('telescope')==[]; i=l.publish(c.candidate_id); assert l.search('telescope')[0].item_id==i.item_id

def test_publish_refuses_tampered_staged_payload(tmp_path:Path):
    s=tmp_path/'x.txt'; s.write_text('original'); l=Library(tmp_path/'lib'); c=l.stage(s,title='X',source='local'); Path(c.staged_path).write_text('tampered');
    with pytest.raises(RuntimeError): l.publish(c.candidate_id)

def test_reject_keeps_audit_record_but_removes_payload(tmp_path:Path):
    s=tmp_path/'x.txt'; s.write_text('candidate'); l=Library(tmp_path/'lib'); c=l.stage(s,title='X',source='local'); p=Path(c.staged_path); r=l.reject(c.candidate_id,'bad source'); assert r.state=='rejected' and r.rejection_reason=='bad source' and not p.exists(); assert l.inspect_candidate(c.candidate_id).state=='rejected'

def test_file_size_limit_blocks_stage(tmp_path:Path):
    s=tmp_path/'big.bin'; s.write_bytes(b'x'*11); l=Library(tmp_path/'lib',max_file_bytes=10)
    with pytest.raises(ValueError): l.stage(s,title='Big',source='local')

def test_large_text_can_archive_without_extraction(tmp_path:Path):
    s=tmp_path/'large.txt'; s.write_text('alpha beta gamma'); l=Library(tmp_path/'lib',max_extract_bytes=4); i=l.add(s,title='Large',source='local'); assert Path(i.storage_path).exists() and i.extracted_text_path is None
