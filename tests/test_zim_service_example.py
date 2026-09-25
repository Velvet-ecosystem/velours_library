from pathlib import Path


def test_zim_systemd_example_is_loopback_only_and_vault_gated():
    unit = Path("examples/systemd/velour-zim.service").read_text(encoding="utf-8")

    assert "ConditionPathIsMountPoint=/srv/velvet" in unit
    assert "ExecStartPre=/usr/local/bin/velour-vault --root /srv/velvet status" in unit
    assert "ExecStartPre=/usr/local/bin/velour-zim --root /srv/velvet/library status" in unit
    assert (
        "ExecStart=/usr/local/bin/velour-zim --root /srv/velvet/library serve "
        "--address 127.0.0.1 --port 8080"
    ) in unit
    assert "--allow-network" not in unit
    assert "--allow-external-links" not in unit
    assert "ReadOnlyPaths=/srv/velvet/library" in unit
