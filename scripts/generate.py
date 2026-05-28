#!/usr/bin/env python3
"""Generate JSON endpoints from data/images.yaml for GitHub Pages."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "images.yaml"
DOCS_DIR = ROOT / "docs" / "v1"

REQUIRED_FIELDS = {"id", "name", "category", "version", "arch", "status", "eol"}
IMAGE_TYPES = {"iso", "cloud-image", "disk-image"}
IMAGE_FORMATS = {
    "iso",
    "qcow2",
    "raw",
    "vhd",
    "vhdx",
    "vmdk",
    "ova",
    "tar",
    "unknown",
}
COMPRESSIONS = {"xz", "gz", "bz2", "zst", "zip"}


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def infer_artifact(url):
    """Infer artifact format and compression from a download URL."""
    if not url:
        return "unknown", None

    path = urlparse(url).path.lower()
    compression = None
    for suffix in (".tar.xz", ".tar.gz", ".tar.bz2", ".tar.zst"):
        if path.endswith(suffix):
            compression = suffix.rsplit(".", 1)[1]
            return "tar", compression

    for suffix in COMPRESSIONS:
        if path.endswith(f".{suffix}"):
            compression = suffix
            path = path[: -(len(suffix) + 1)]
            break

    if path.endswith(".iso"):
        return "iso", compression
    if path.endswith(".qcow2"):
        return "qcow2", compression
    if path.endswith(".raw"):
        return "raw", compression
    if path.endswith(".img"):
        return "raw", compression
    if path.endswith(".vhd"):
        return "vhd", compression
    if path.endswith(".vhdx"):
        return "vhdx", compression
    if path.endswith(".vmdk"):
        return "vmdk", compression
    if path.endswith(".ova"):
        return "ova", compression

    return "unknown", compression


def infer_image_type(image_format):
    if image_format == "iso":
        return "iso"
    if image_format == "unknown":
        return "iso"
    return "disk-image"


def normalize(images):
    for img in images:
        inferred_format, inferred_compression = infer_artifact(img.get("url"))

        image_format = img.get("format") or inferred_format
        img["format"] = image_format

        if inferred_compression and "compression" not in img:
            img["compression"] = inferred_compression

        if "image_type" not in img:
            img["image_type"] = infer_image_type(image_format)


def validate(images):
    errors = []
    ids = set()
    for i, img in enumerate(images):
        for field in REQUIRED_FIELDS:
            if field not in img or img[field] is None:
                errors.append(f"Image #{i} ({img.get('id', '?')}): missing '{field}'")
        if "url" not in img and "download_page" not in img:
            errors.append(f"Image #{i} ({img.get('id', '?')}): needs 'url' or 'download_page'")
        image_type = img.get("image_type")
        if image_type not in IMAGE_TYPES:
            errors.append(
                f"Image #{i} ({img.get('id', '?')}): invalid image_type '{image_type}'"
            )
        image_format = img.get("format")
        if image_format not in IMAGE_FORMATS:
            errors.append(
                f"Image #{i} ({img.get('id', '?')}): invalid format '{image_format}'"
            )
        compression = img.get("compression")
        if compression is not None and compression not in COMPRESSIONS:
            errors.append(
                f"Image #{i} ({img.get('id', '?')}): invalid compression '{compression}'"
            )
        if image_type == "iso" and image_format not in {"iso", "unknown"}:
            errors.append(
                f"Image #{i} ({img.get('id', '?')}): ISO image_type cannot use format '{image_format}'"
            )
        img_id = img.get("id")
        if img_id in ids:
            errors.append(f"Duplicate id: {img_id}")
        ids.add(img_id)
    return errors


def make_envelope(images, generated_at):
    return {
        "meta": {
            "api_version": "v1",
            "generated_at": generated_at,
            "count": len(images),
        },
        "images": images,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    if not DATA_FILE.exists():
        print(f"ERROR: {DATA_FILE} not found", file=sys.stderr)
        sys.exit(1)

    data = load_data()
    images = data.get("images", [])
    normalize(images)

    errors = validate(images)
    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Collect unique architectures for dynamic arch filters
    arches = {img["arch"] for img in images}
    # Normalize arch names for filenames (amd64, arm64, x86_64, x64 etc.)
    arch_normalize = {
        "amd64": {"amd64", "x86_64", "x64"},
        "arm64": {"arm64", "aarch64"},
        "riscv64": {"riscv64"},
    }

    # Generate filtered endpoints
    filters = {
        "all.json": lambda _: True,
        "supported.json": lambda img: img["status"] in ("supported", "beta"),
        "eol.json": lambda img: img["status"] in ("eol", "eol-extended"),
        "linux.json": lambda img: img["category"] == "linux",
        "windows.json": lambda img: img["category"] == "windows",
        "bsd.json": lambda img: img["category"] == "bsd",
        "iso.json": lambda img: img["image_type"] == "iso",
        "cloud-images.json": lambda img: img["image_type"] == "cloud-image",
        "disk-images.json": lambda img: img["image_type"] == "disk-image",
    }

    # Add arch-based filters dynamically
    for arch_key, arch_variants in arch_normalize.items():
        if arch_variants & arches:
            filters[f"{arch_key}.json"] = (
                lambda img, av=arch_variants: img["arch"] in av
            )

    for filename, predicate in filters.items():
        filtered = [img for img in images if predicate(img)]
        output = make_envelope(filtered, now)
        write_json(DOCS_DIR / filename, output)
        print(f"  {filename}: {len(filtered)} images")

    print(f"\nGenerated {len(filters)} JSON files with {len(images)} total images.")


if __name__ == "__main__":
    main()
