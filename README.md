# OS Image Catalog

Machine-readable catalog of OS installation media, cloud images, and disk images with download URLs, checksums, formats, and EOL dates.

Served as static JSON via GitHub Pages. Updated daily via GitHub Actions.

[![Daily Checks](https://github.com/MuNeNICK/os-iso-catalog/actions/workflows/daily-check.yml/badge.svg)](https://github.com/MuNeNICK/os-iso-catalog/actions/workflows/daily-check.yml)

## Web UI

Browse the catalog with filtering, search, and EOL status at a glance:

- **Dashboard**: https://munenick.github.io/os-iso-catalog/
- **API Docs (Swagger)**: https://munenick.github.io/os-iso-catalog/api.html

<img width="1267" height="993" alt="image" src="https://github.com/user-attachments/assets/8865f535-4fda-4df5-9c8e-982db8219dc8" />


## API Endpoints

Base URL: `https://MuNeNICK.github.io/os-iso-catalog`

| Endpoint | Description |
|----------|-------------|
| `/v1/all.json` | All OS images |
| `/v1/supported.json` | Currently supported only |
| `/v1/eol.json` | End-of-life archive |
| `/v1/linux.json` | Linux distributions |
| `/v1/windows.json` | Windows images |
| `/v1/bsd.json` | BSD family |
| `/v1/iso.json` | ISO installation media |
| `/v1/cloud-images.json` | Cloud images |
| `/v1/disk-images.json` | Disk images |
| `/v1/amd64.json` | amd64/x86_64 images |
| `/v1/arm64.json` | arm64/aarch64 images |

## Quick Start

```bash
# Get all supported Linux images
curl -s https://MuNeNICK.github.io/os-iso-catalog/v1/supported.json \
  | jq '.images[] | select(.category == "linux") | {name, url}'
```

## Coverage

- **Linux**: Ubuntu, Kubuntu, Xubuntu, Debian, Fedora, Rocky Linux, AlmaLinux, CentOS Stream, openSUSE (Leap/Tumbleweed), Linux Mint, Arch, Manjaro, Kali, Alpine, Gentoo, Oracle Linux, Amazon Linux, Raspberry Pi OS, MX Linux, Pop!_OS, CachyOS, EndeavourOS, NixOS, Slackware, Tails, Qubes OS, Zorin OS, Omarchy
- **Windows**: Windows 11, 10, Server 2025/2022/2019
- **BSD**: FreeBSD, OpenBSD, NetBSD

All currently supported versions are tracked.

## How It Works

1. `data/images.yaml` is the single source of truth
2. `scripts/generate.py` transforms YAML into filtered JSON endpoints under `docs/v1/`
3. GitHub Pages serves the `docs/` directory
4. **Daily at 06:00 UTC**, GitHub Actions:
   - **Auto-update**: Detects new releases and version updates via URL templates, creates a PR for review
   - **EOL check**: Fetches EOL dates from [endoflife.date](https://endoflife.date/) API and auto-updates `status` field
   - **Link check**: Validates all download URLs are reachable, creates Issues for broken links
   - **New release check**: Detects new OS releases for manual-only distros, creates Issues

## Auto-update

`scripts/auto_update.py` uses URL templates defined in `data/images.yaml` to automatically detect new releases, update download URLs and checksums, and add new entries. Changes are submitted as a Pull Request for human review.

Cloud image entries use the same tracking system where upstream URLs and checksum files are predictable. Ubuntu, Debian, Fedora, Alpine, and Amazon Linux cloud images are template-driven; rolling/latest images are link-checked and checksum automation is added per distro when the upstream format is stable enough.

### Template types

| Type | Description | Used by |
|------|-------------|---------|
| `static` | URL is fully predictable from version | Ubuntu, Debian, AlmaLinux, Alpine, FreeBSD, OpenBSD, NetBSD, Oracle Linux |
| `directory_parse` | Filename resolved from directory listing (e.g. build numbers) | Fedora, Rocky Linux |
| `rolling_checksum` | Refreshes checksums for rolling "latest" URLs | CentOS Stream |

### Coverage

| Distro | Auto-update | Reason |
|--------|:-----------:|--------|
| Ubuntu | Yes | Static URL pattern |
| Debian | Yes | Static URL pattern |
| Fedora | Yes | Directory parse (build numbers in filename) |
| Rocky Linux | Yes | Directory parse (dvd/dvd1 naming) |
| AlmaLinux | Yes | Static URL pattern |
| CentOS Stream | Yes | Rolling checksum refresh |
| Alpine | Yes | Static URL pattern |
| FreeBSD | Yes | Static URL pattern |
| OpenBSD | Yes | Static URL pattern |
| NetBSD | Yes | Static URL pattern |
| Oracle Linux | Yes | Static URL pattern |
| openSUSE | No | Complex naming (Leap 15 vs 16 differ significantly) |
| Linux Mint | No | SourceForge-hosted, no predictable URL pattern |
| Arch Linux | No | Rolling release, manual tracking |
| Manjaro | No | Date-based filenames with kernel version |
| Kali Linux | No | No endoflife.date API coverage |
| Gentoo | No | Date-based autobuild filenames |
| Others | No | Irregular release patterns or no API coverage |

## Contributing

1. Edit `data/images.yaml`
2. Run `python scripts/generate.py` to verify
3. Submit a PR

### Adding a new image

```yaml
- id: distro-version-edition
  name: "Distro Name Version"
  category: linux          # linux | windows | bsd
  distro: distro-slug
  version: "1.0"
  arch: amd64
  release_type: stable     # stable | beta | rolling
  image_type: iso          # iso | cloud-image | disk-image
  format: iso              # iso | qcow2 | raw | tar | ...
  url: https://example.com/distro.iso
  checksum:
    algorithm: sha256
    value: "abc123..."
  eol:
    standard: "2030-01-01"
    extended: null
    is_rolling: false
  status: supported        # supported | eol | eol-extended | beta
```

## Acknowledgments

- [endoflife.date](https://endoflife.date/) — EOL date data and new release detection

## License

MIT
