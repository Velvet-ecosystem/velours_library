# Automatic staged intake

For a Linux Founder/Home deployment, a systemd path unit can turn a vault drop folder into a guarded loading dock without making publication automatic.

Example units live under:

```text
examples/systemd/velour-library-drop.path
examples/systemd/velour-library-drop.service
```

The example watches:

```text
/srv/velvet/staging/library-drop
```

and runs `velour-ingest` whenever that directory changes.

The service deliberately omits `--publish`. New material therefore becomes a normal staged candidate and remains invisible to ordinary retrieval until it is reviewed and published through the existing Library workflow.

The example also:

- requires `/srv/velvet` to be a mounted filesystem
- runs as the unprivileged `velvet` account
- uses a private temporary directory
- denies new privileges
- protects the host filesystem except for the explicit Library/drop paths
- disables ordinary network address families because local batch intake does not need Internet access
- assigns stable `vault://staging/library-drop/...` source URIs instead of leaking absolute operator paths into provenance

Before enabling it, create the drop folder and make ownership match the Velvet service account:

```bash
sudo mkdir -p /srv/velvet/staging/library-drop
sudo chown velvet:velvet /srv/velvet/staging/library-drop
```

Install the example units using the deployment's normal configuration-management path, review the paths/user first, then enable the `.path` unit.

OCR is intentionally not enabled in the generic watcher example. A deployment that wants unattended OCR should first install and validate its local OCRmyPDF/Tesseract toolchain and resource limits, then add `--ocr` deliberately.
