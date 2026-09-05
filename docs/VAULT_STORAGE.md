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

The production `velour-vault` entry point independently checks that `/srv/velvet` is an actual mountpoint and returns a fail-closed `vault-unavailable` result when it is not. Non-production roots remain available for tests and development.

The initializer writes `.velvet-vault.json` into the vault root. Runtime uses that manifest as the presence sentinel for the attached vault.

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

`os.statvfs()` reports the same filesystem capacity for the manifest file. If the external vault is removed, the manifest disappears, so the next Runtime resource probe omits `storage.vault-1tb` rather than accidentally reporting Founder's underlying filesystem as the vault.

The runtime resource record describes capacity only. It does not expose vault content and carries no authority.

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
