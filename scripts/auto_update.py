#!/usr/bin/env python3
"""Auto-update image catalog entries using URL templates and endoflife.date API.

For distros with update_templates in tracking config:
  - Detects new major versions and adds entries
  - Updates existing entries when point releases come out
  - Refreshes checksums for rolling releases

Template types:
  - static: URL fully predictable from version
  - directory_parse: Needs to fetch directory listing to resolve filenames
"""

import re
import sys
from datetime import date
from pathlib import Path

import requests
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "images.yaml"
REPORT_FILE = ROOT / "auto-update-report.txt"

EOL_API = "https://endoflife.date/api"
TIMEOUT = 15
USER_AGENT = "os-iso-catalog/auto-update (github.com/MuNeNICK/os-iso-catalog)"


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def load_data():
    y = YAML()
    y.preserve_quotes = True
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return y, y.load(f)


def save_data(y, data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        y.dump(data, f)


# ---------------------------------------------------------------------------
# endoflife.date API
# ---------------------------------------------------------------------------

def fetch_api_releases(product):
    """Fetch all release cycles from endoflife.date."""
    try:
        r = requests.get(f"{EOL_API}/{product}.json",
                         timeout=TIMEOUT,
                         headers={"User-Agent": USER_AGENT})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"  WARN: API fetch failed for {product}: {e}", file=sys.stderr)
    return []


def is_eol_past(eol_value):
    if eol_value is True:
        return True
    if isinstance(eol_value, str):
        try:
            return date.fromisoformat(eol_value) < date.today()
        except ValueError:
            pass
    return False


def is_release_past_supported_life(rel):
    """Return true only when both standard and extended support have ended."""
    extended = rel.get("extendedSupport")
    if isinstance(extended, str):
        return is_eol_past(extended)
    return is_eol_past(rel.get("eol", False))


def extract_eol_dates(rel):
    """Extract standard and extended EOL dates from API release."""
    api_eol = rel.get("eol")
    api_support = rel.get("support")
    api_extended = rel.get("extendedSupport")

    standard = None
    extended = None

    if api_extended and isinstance(api_extended, str):
        if isinstance(api_eol, str):
            standard = api_eol
        extended = api_extended
    elif (api_support and isinstance(api_support, str)
          and api_eol and isinstance(api_eol, str)
          and api_support != api_eol):
        standard = api_support
        extended = api_eol
    elif isinstance(api_eol, str):
        standard = api_eol

    return standard, extended


def filter_releases(releases, rules):
    """Filter API releases using tracking rules."""
    lts_only = rules.get("lts_only", False)
    exclude_cycles = rules.get("exclude_cycles", [])
    filtered = []
    for rel in releases:
        if is_release_past_supported_life(rel):
            continue
        cycle = str(rel.get("cycle", ""))
        if not cycle:
            continue
        if any(__import__("fnmatch").fnmatch(cycle, p) for p in exclude_cycles):
            continue
        if lts_only and not rel.get("lts", False):
            continue
        filtered.append(rel)
    return filtered


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def make_version_vars(cycle, latest, codename=None):
    """Build template variable dict from version info."""
    cycle_str = str(cycle)
    latest_str = str(latest)
    latest_parts = latest_str.split(".")
    codename_str = codename or ""
    codename_slug = codename_str.split()[0].lower() if codename_str else ""

    return {
        "cycle": cycle_str,
        "latest": latest_str,
        "major": latest_parts[0] if latest_parts else cycle_str,
        "minor": latest_parts[1] if len(latest_parts) > 1 else "",
        "patch": latest_parts[2] if len(latest_parts) > 2 else "",
        "codename": codename_str,
        "codename_slug": codename_slug,
        "version_no_dots": cycle_str.replace(".", ""),
    }


def render(template_str, variables):
    """Render a template string with variables."""
    result = template_str
    for key, val in variables.items():
        result = result.replace(f"{{{key}}}", str(val))
    return result


# ---------------------------------------------------------------------------
# Checksum fetching
# ---------------------------------------------------------------------------

def parse_checksum_line(line, target_filename):
    """Parse a checksum line in GNU or BSD format."""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-----"):
        return None

    # BSD format: SHA256 (filename) = hash
    m = re.match(r"\w+\s+\((.+?)\)\s*=\s*([0-9a-fA-F]+)", line)
    if m and m.group(1) == target_filename:
        return m.group(2).lower()

    # GNU format: hash  filename  or  hash *filename
    m = re.match(r"([0-9a-fA-F]+)\s+\*?(.+)", line)
    if m and m.group(2).strip() == target_filename:
        return m.group(1).lower()

    # Single-hash files such as Alpine's .sha256/.sha512 sidecars.
    if re.fullmatch(r"[0-9a-fA-F]{32,}", line):
        return line.lower()

    return None


def fetch_checksum(checksums_url, target_filename):
    """Download a checksums file and extract the hash for target_filename."""
    try:
        r = requests.get(checksums_url, timeout=TIMEOUT,
                         headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            return None
        for line in r.text.splitlines():
            h = parse_checksum_line(line, target_filename)
            if h:
                return h
    except Exception as e:
        print(f"  WARN: checksum fetch failed {checksums_url}: {e}",
              file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Directory listing parser
# ---------------------------------------------------------------------------

def resolve_directory_filename(dir_url, filename_regex):
    """Fetch a directory listing and find file matching regex."""
    try:
        r = requests.get(dir_url, timeout=TIMEOUT,
                         headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            return None, None
        # Extract href values from HTML
        hrefs = re.findall(r'href="([^"]+)"', r.text)
        pattern = re.compile(filename_regex)
        for href in hrefs:
            fname = href.rstrip("/").split("/")[-1]
            m = pattern.match(fname)
            if m:
                return fname, m
    except Exception as e:
        print(f"  WARN: directory fetch failed {dir_url}: {e}",
              file=sys.stderr)
    return None, None


# ---------------------------------------------------------------------------
# Image entry management
# ---------------------------------------------------------------------------

def find_image(images, image_id):
    """Find an image by ID, return index and entry."""
    for i, img in enumerate(images):
        if img.get("id") == image_id:
            return i, img
    return None, None


def find_insert_position(images, distro):
    """Find the best position to insert a new entry for a distro."""
    last_idx = -1
    for i, img in enumerate(images):
        if img.get("distro") == distro:
            last_idx = i
    return last_idx + 1 if last_idx >= 0 else len(images)


def build_new_entry(variant, variables, url, checksum_value,
                    templates_config, rel, distro):
    """Build a new image entry dict."""
    algorithm = variant.get(
        "checksum_algorithm", templates_config.get("checksum_algorithm", "sha256")
    )
    std_eol, ext_eol = extract_eol_dates(rel)
    is_rolling = rel.get("eol") is False or templates_config.get(
        "rolling_checksum", False)
    release_type = "rolling" if is_rolling else "stable"
    version = render(variant.get("version_template", "{latest}"), variables)

    entry = {
        "id": render(variant["id_template"], variables),
        "name": render(variant["name_template"], variables),
        "category": templates_config.get("category", "linux"),
        "distro": distro,
        "version": version,
        "edition": variant.get("edition", ""),
        "arch": variant["arch"],
        "release_type": release_type,
        "url": url,
        "homepage": templates_config.get("homepage", ""),
    }

    for field in ("image_type", "format", "compression"):
        if variant.get(field):
            entry[field] = variant[field]

    codename = variables.get("codename")
    if codename:
        entry["codename"] = codename

    if checksum_value:
        entry["checksum"] = {
            "algorithm": algorithm,
            "value": checksum_value,
        }

    entry["eol"] = {
        "standard": std_eol,
        "extended": ext_eol,
        "is_rolling": is_rolling,
    }

    # Determine status based on EOL dates
    today = date.today()
    std_date = None
    ext_date = None
    if std_eol:
        try:
            std_date = date.fromisoformat(str(std_eol))
        except (ValueError, TypeError):
            pass
    if ext_eol:
        try:
            ext_date = date.fromisoformat(str(ext_eol))
        except (ValueError, TypeError):
            pass

    if std_date and today > std_date:
        if ext_date and today <= ext_date:
            entry["status"] = "eol-extended"
        elif ext_date and today > ext_date:
            entry["status"] = "eol"
        else:
            entry["status"] = "eol"
    else:
        entry["status"] = "supported"

    return entry


def update_image(img, url, checksum_value, new_version, new_name,
                 algorithm="sha256", variant=None):
    """Update mutable fields of an existing image. Returns list of changes."""
    changes = []
    img_id = img["id"]

    if new_version and str(img.get("version", "")) != str(new_version):
        old_v = img.get("version", "?")
        img["version"] = new_version
        changes.append(f"{img_id}: version {old_v} -> {new_version}")

    if new_name and str(img.get("name", "")) != str(new_name):
        img["name"] = new_name

    if url and str(img.get("url", "")) != str(url):
        img["url"] = url
        if changes:
            changes.append(f"{img_id}: url updated")
        else:
            changes.append(f"{img_id}: url updated")

    if checksum_value:
        cs = img.get("checksum", {})
        old_val = str(cs.get("value", ""))
        if old_val != checksum_value:
            img["checksum"] = {"algorithm": algorithm, "value": checksum_value}
            changes.append(f"{img_id}: checksum updated")

    if variant:
        for field in ("image_type", "format", "compression"):
            value = variant.get(field)
            if value and img.get(field) != value:
                img[field] = value
                changes.append(f"{img_id}: {field} updated")

    return changes


# ---------------------------------------------------------------------------
# URL reachability check
# ---------------------------------------------------------------------------

def url_exists(url):
    """Quick HEAD check to see if a URL is reachable."""
    try:
        r = requests.head(url, timeout=TIMEOUT, allow_redirects=True,
                          headers={"User-Agent": USER_AGENT})
        return r.status_code < 400
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Processing logic
# ---------------------------------------------------------------------------

def process_static(distro, rules, templates, images, releases):
    """Process static-template distros."""
    changes = []
    match_depth = rules.get("match_depth", 1)
    base_algorithm = templates.get("checksum_algorithm", "sha256")

    for rel in releases:
        cycle = str(rel.get("cycle", ""))
        latest = str(rel.get("latest", cycle))
        codename = rel.get("codename", "")
        variables = make_version_vars(cycle, latest, codename)

        for variant in templates.get("variants", []):
            image_id = render(variant["id_template"], variables)
            url = render(variant["url_template"], variables)
            name = render(variant["name_template"], variables)
            version = render(variant.get("version_template", "{latest}"), variables)
            algorithm = variant.get("checksum_algorithm", base_algorithm)

            # Resolve checksum
            checksum_value = None
            checksums_url = variant.get("checksums_url")
            filename_pattern = variant.get("filename_pattern")
            if checksums_url and filename_pattern:
                cs_url = render(checksums_url, variables)
                cs_file = render(filename_pattern, variables)
                checksum_value = fetch_checksum(cs_url, cs_file)

            idx, existing = find_image(images, image_id)
            if existing:
                # Update existing entry
                ch = update_image(existing, url, checksum_value,
                                  version, name, algorithm, variant)
                changes.extend(ch)
            else:
                # Check URL exists before adding
                if url_exists(url):
                    entry = build_new_entry(
                        variant, variables, url, checksum_value,
                        templates, rel, distro)
                    pos = find_insert_position(images, distro)
                    images.insert(pos, entry)
                    changes.append(f"{image_id}: NEW entry added")
                else:
                    print(f"  SKIP {image_id}: URL not reachable: {url}",
                          file=sys.stderr)

    return changes


def process_directory_parse(distro, rules, templates, images, releases):
    """Process directory-parse-template distros."""
    changes = []
    base_algorithm = templates.get("checksum_algorithm", "sha256")

    for rel in releases:
        cycle = str(rel.get("cycle", ""))
        latest = str(rel.get("latest", cycle))
        codename = rel.get("codename", "")
        variables = make_version_vars(cycle, latest, codename)

        for variant in templates.get("variants", []):
            image_id = render(variant["id_template"], variables)

            # Resolve filename from directory listing
            dir_url = render(variant["dir_url"], variables)
            fname_regex = render(variant["filename_regex"], variables)
            filename, match = resolve_directory_filename(dir_url, fname_regex)
            if not filename:
                print(f"  SKIP {image_id}: no file found at {dir_url}",
                      file=sys.stderr)
                continue

            # Build final URL
            url = dir_url.rstrip("/") + "/" + filename
            name = render(variant["name_template"], variables)
            version = render(variant.get("version_template", "{latest}"), variables)
            algorithm = variant.get("checksum_algorithm", base_algorithm)

            # Resolve checksum
            checksum_value = None
            checksums_url = variant.get("checksums_url")
            if checksums_url:
                cs_url = render(checksums_url, variables)
                # For directory-parse, try fetching from rendered URL
                # If it contains a glob/wildcard, resolve it too
                if "*" in cs_url:
                    cs_dir = cs_url.rsplit("/", 1)[0] + "/"
                    cs_pattern = cs_url.rsplit("/", 1)[1].replace(
                        "*", ".*")
                    cs_filename, _ = resolve_directory_filename(
                        cs_dir, cs_pattern)
                    if cs_filename:
                        cs_url = cs_dir + cs_filename
                checksum_value = fetch_checksum(cs_url, filename)

            idx, existing = find_image(images, image_id)
            if existing:
                ch = update_image(existing, url, checksum_value,
                                  version, name, algorithm, variant)
                changes.extend(ch)
            else:
                if url_exists(url):
                    entry = build_new_entry(
                        variant, variables, url, checksum_value,
                        templates, rel, distro)
                    pos = find_insert_position(images, distro)
                    images.insert(pos, entry)
                    changes.append(f"{image_id}: NEW entry added")
                else:
                    print(f"  SKIP {image_id}: URL not reachable: {url}",
                          file=sys.stderr)

    return changes


def process_rolling_checksum(distro, templates, images):
    """Refresh checksums for rolling release entries."""
    changes = []
    algorithm = templates.get("checksum_algorithm", "sha256")

    for variant in templates.get("variants", []):
        # For rolling, the id_template may have {cycle} placeholders
        # Find all matching images by distro + edition + arch
        edition = variant.get("edition", "")
        arch = variant["arch"]
        image_type = variant.get("image_type")
        image_format = variant.get("format")

        for img in images:
            if (img.get("distro") != distro
                    or img.get("edition") != edition
                    or img.get("arch") != arch):
                continue
            if image_type and img.get("image_type") != image_type:
                continue
            if image_format and img.get("format") != image_format:
                continue

            checksums_url = variant.get("checksums_url")
            filename_pattern = variant.get("filename_pattern")
            if not checksums_url or not filename_pattern:
                continue

            # Build variables from existing image
            version = str(img.get("version", ""))
            variables = make_version_vars(version, version)
            cs_url = render(checksums_url, variables)
            cs_file = render(filename_pattern, variables)
            checksum_value = fetch_checksum(cs_url, cs_file)

            if checksum_value:
                ch = update_image(img, None, checksum_value,
                                  None, None, algorithm, variant)
                changes.extend(ch)

    return changes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    y, data = load_data()
    images = data.get("images", [])
    tracking = data.get("tracking", {})

    all_changes = []
    print("Running auto-update...")

    for distro, rules in tracking.items():
        templates = rules.get("update_templates")
        if not templates:
            continue

        product = rules.get("product")
        ttype = templates.get("type", "static")

        print(f"  Processing {distro} ({ttype})...")

        if templates.get("rolling_checksum"):
            changes = process_rolling_checksum(distro, templates, images)
        else:
            releases = fetch_api_releases(product) if product else []
            releases = filter_releases(releases, rules)

            if ttype == "static":
                changes = process_static(
                    distro, rules, templates, images, releases)
            elif ttype == "directory_parse":
                changes = process_directory_parse(
                    distro, rules, templates, images, releases)
            else:
                continue

        all_changes.extend(changes)

    if all_changes:
        save_data(y, data)
        print(f"\nChanges ({len(all_changes)}):")
        for c in all_changes:
            print(f"  {c}")

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(all_changes) + "\n")

        sys.exit(2)
    else:
        print("\nNo updates needed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
