# Velvet Local Vault

The local vault is the deployment storage root for large, persistent Velvet data such as Library material, receipt archives, video, images, audio, models, maps, snapshots, and diagnostic history.

It is storage, not authority. Mounting a larger disk does not change identity, Court policy, execution permission, trust, or truth status.

## Recommended Founder layout

The initial Founder deployment uses one encrypted Linux filesystem mounted at:

```text
/srv/velvet
```

Velour's Library then uses:

```text
/srv/velvet/library
```

as its deployment `--root`. Canonical receipt producers remain owned by `velvet-receipts`; the vault may retain their archive files under `/srv/velvet/receipts`.

The vault initializer creates this logical layout:

```text
/srv/velvet/
├── library/
├── receipts/
├── media/
│   ├── video/
│   │   ├── rolling/
│   │   ├── events/
│   │   ├── security/
│   │   ├── emergency/
│   │   └── retained/
│   ├── images/
│   └── audio/
├── models/
├── maps/
├── snapshots/
├── logs/
├── staging/
├── quarantine/
├── backup/
└── catalog/
```

These are directories, not fixed-size partitions. One filesystem lets storage move between workloads without artificial partition walls.

## Retention classes

`velour-vault` defines five storage-retention classes:

| Class | Meaning | Automatic purge |
|---|---|---|
| `CACHE` | Rebuildable scratch/cache material | permitted |
| `ROLLING` | Short-lived ring/rolling capture | permitted |
| `STANDARD` | Ordinary retained material | not permitted |
| `PROTECTED` | Evidence or owner-protected material | forbidden |
| `PERMANENT` | Permanent archive/critical record | forbidden |

The library does not currently delete anything automatically. `may_auto_purge()` is a policy boundary for future cleanup workers. A cleanup worker must never infer that all old data is disposable.

Retention can be promoted but not downgraded through the vault catalog.

## Capacity guard

Default policy:

```text
cleanup trigger: 15% free
hard reserve:    10% free
```

Above 15% free, vault health is `healthy`.

At or below 15% free, vault health becomes `cleanup_due`.

At or below 10% free, vault health becomes `reserve_guard`.

The reserve exists so a camera burst, emergency incident, receipt append, or database update does not discover a completely full filesystem at the worst possible moment.

## Cross-media catalog

`catalog/vault.sqlite3` is a rebuildable local catalog for files outside the Library's knowledge catalog.

A catalog entry stores references, not duplicate payloads:

```text
object_id
kind
path
created
source
classification
retention
sha256
related_event
related_receipt
tags
```

The SHA-256 binds a catalog entry to the bytes currently stored at that path. `velour-vault verify <object-id>` recalculates the digest and reports whether the object still matches.

The catalog grants no authority and does not replace canonical Velvet receipts. A receipt may point at a vault object; a vault object does not make a receipt valid.

## Safe initialization

Initialize only after the encrypted filesystem is positively mounted at `/srv/velvet`:

```bash
findmnt --mountpoint /srv/velvet
velour-vault --root /srv/velvet init
velour-vault --root /srv/velvet status
```

The production `velour-vault` entry point requires an explicit expected mounted-filesystem UUID and returns `vault-unavailable` for missing, wrong, ambiguous or unverifiable identity. Configure `VELVET_VAULT_FILESYSTEM_UUID` or supply `--expected-filesystem-uuid` before the command. A mountpoint alone is insufficient. Non-production roots remain available for tests and development unless an expected UUID is explicitly configured. Production subdirectories require identity as well; verified subdirectories and bind mounts are supported.

The initializer writes `.velvet-vault.json` into the vault root. Runtime may probe that file, but verifies its backing filesystem UUID; the marker is not identity.

Register an existing media object:

```bash
velour-vault --root /srv/velvet register \
  media/video/rolling/front-001.mp4 \
  --kind video \
  --source camera.front \
  --retention ROLLING \
  --tag front
```

Promote evidence:

```bash
velour-vault --root /srv/velvet promote <object-id> PROTECTED
```

Verify the retained bytes:

```bash
velour-vault --root /srv/velvet verify <object-id>
```

## Initial 1 TB device provisioning

The `velour-vault` command intentionally does **not** partition, format, encrypt, unlock, or erase block devices.

Provisioning a new drive is a separate operator action because choosing the wrong `/dev/...` device is destructive.

First identify the drive by size, model, and serial:

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS
```

Only after the target device has been positively identified, an initial Linux deployment can use:

```text
GPT
└── one data partition
    └── LUKS2
        └── ext4
            └── /srv/velvet
```

Example commands below use `/dev/sdX`. Replace that placeholder only after checking the real device.

```bash
sudo umount /dev/sdX?* 2>/dev/null || true
sudo parted /dev/sdX --script mklabel gpt
sudo parted /dev/sdX --script mkpart VELVET_VAULT 1MiB 100%

sudo cryptsetup luksFormat --type luks2 /dev/sdX1
sudo cryptsetup open /dev/sdX1 velvet_vault_crypt

sudo mkfs.ext4 -L VELVET_VAULT -m 0 /dev/mapper/velvet_vault_crypt
sudo mkdir -p /srv/velvet
sudo mount /dev/mapper/velvet_vault_crypt /srv/velvet
```

Set ownership on the mounted filesystem to the deployment account that runs the Library and archive writers, then initialize the logical vault.

For the first bench bring-up, manual LUKS unlock is preferred. Unattended key storage is deployment-specific and should not be hidden in this public repository. Recovery material should be kept separately from the Founder.

For persistent mounting, use filesystem/LUKS UUIDs rather than `/dev/sdX` names. USB device names can change between boots.

### Guard the bare mountpoint

A mountpoint directory still exists on Founder's internal filesystem when the external vault is absent. That creates a dangerous failure mode if a service writes to `/srv/velvet` while the drive is unmounted: the bytes would silently land on internal storage.

After creating the empty mountpoint and before mounting the vault, make the underlying directory non-writable to ordinary services:

```bash
sudo mkdir -p /srv/velvet
sudo chown root:root /srv/velvet
sudo chmod 000 /srv/velvet
```

Then mount the ext4 vault. The mounted filesystem has its own root ownership and permissions, so configure those while it is mounted for the `velvet` service account. When the vault disappears, the protected underlying mountpoint is exposed again and ordinary archive writers fail closed instead of filling Founder's eMMC.

This mountpoint guard does not replace checking the actual mount during provisioning. Use `findmnt --mountpoint`, `lsblk`, and UUID-based mount configuration as the source of physical-device truth.

## Runtime resource advertisement

`velvet-runtime` already supports explicit attached filesystem resources. The mounted vault remains `/srv/velvet`, but Runtime should probe:

```text
/srv/velvet/.velvet-vault.json
```

rather than the bare `/srv/velvet` directory.

Runtime's attached storage entry must also contain `expected_filesystem_uuid` for the positively identified mounted filesystem. Missing/path-only, wrong, ambiguous or unverifiable identity makes the resource unavailable, even if the directory or marker survives. Do not use the USB name, capacity, generic marker, or encrypted-container UUID in place of the mounted filesystem UUID.

The runtime resource record describes capacity only. It does not expose vault content and carries no authority.

### Matching production write checks

`VaultManager` checks the same UUID/mount/device binding before each production
operation, including initialization, catalog changes and health observations.
It holds a verified directory descriptor during the operation, uses that
reference for filesystem access, checks for path replacement/disappearance,
and rejects nested paths on another filesystem or through symlinks. Public
paths, catalog records, manifest and receipt formats remain unchanged. It does
not create a missing verified root on the host. Each later operation verifies
again, so recovery requires the correct volume to return.

The matching bounded verifier lives in `velours_library.filesystem_identity`
and Runtime's `services/filesystem_identity.py`. Both use Linux procfs and
util-linux `lsblk` with explicit JSON device/UUID columns, a timeout, and no
privilege escalation. Unreadable metadata fails closed. This binds a logical
filesystem, not a cryptographic physical USB identity; cloned/ambiguous UUIDs
are not automatically disambiguated.

Configure the actual UUID locally after positive identification; no UUID is
generated or supplied by the software pass. For an encrypted vault, use the
filesystem inside the unlocked volume. Set the same value in Runtime and the
Library service environment. For example, `/etc/velvet/vault.env` contains the
operator-assigned `VELVET_VAULT_FILESYSTEM_UUID` value and is managed by the local
administrator. The automated drop-folder service reads that file and runs
`velour-vault --root /srv/velvet status` as an additional identity preflight.
Keep its existing mountpoint condition, unprivileged user and writable-path
restrictions. The protected underlying mountpoint remains required, especially
for direct ingestion/archive producers outside `velour-vault`; an advertisement
is never a filesystem write lock. Arbitrary caller-selected development roots
and standalone ingestion APIs are not reclassified as production storage.

No catalog/data migration is needed. Missing configuration deliberately disables
verified vault use; it does not redirect writes. Software tests simulate
kernel/device observations around real temporary files, including replacement
mid-operation. They do not establish physical hotplug or complete hardware
acceptance. Operations are not made into new multi-file transactions by this
repair; partial work, if interrupted, remains subject to the existing recovery
semantics on the intended filesystem.

Recommended capabilities for the shared vault resource are:

```text
vault.storage
library.archive
receipts.archive
media.archive
```

If the drive disappears, the next Runtime resource advertisement should omit it. Velvet can then continue on internal storage in degraded mode rather than pretending the vault is still present.

## Failure posture

The vault is not Velvet's brain stem.

Founder internal storage must retain enough Runtime, Court, continuity, hardware support, and emergency behavior to boot without the vault.

Expected failure behavior:

```text
vault present
    -> normal archive/library/media capability

vault absent or locked
    -> archive capability unavailable
    -> Runtime remains alive
    -> degraded storage condition can be surfaced
    -> ordinary vault writes fail closed at the protected mountpoint
    -> no fictional capacity is advertised
```

A missing vault should reduce memory and archive capability, not erase Velvet's ability to wake, reason about the failure, or preserve immediate safety behavior.
