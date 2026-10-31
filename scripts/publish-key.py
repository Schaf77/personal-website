#!/usr/bin/env python3
"""Prepare public-key downloads and direct-method WKD files for this Hugo site."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ZBASE32 = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", "ybndrfg8ejkmcpqxot1uwisza345h769")


def wkd_hash(local_part):
    digest = hashlib.sha1(local_part.lower().encode("ascii")).digest()
    return base64.b32encode(digest).decode("ascii").translate(ZBASE32)


def key_date(timestamp):
    return datetime.fromtimestamp(int(timestamp), timezone.utc).date().isoformat() if timestamp else "Does not expire"


def run_gpg(home, *args):
    result = subprocess.run(
        ["gpg", "--no-options", "--homedir", home, "--batch", "--no-tty", *args],
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def prepare(email, key_file, root=ROOT):
    # A deliberately conservative mailbox syntax also keeps the GPG filter literal.
    if not re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", email):
        raise ValueError("Use a simple ASCII email address (letters, numbers, dots, _, +, %, or -).")
    local, domain = email.lower().split("@")
    if local.startswith(".") or local.endswith(".") or ".." in local or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in domain.split(".")
    ):
        raise ValueError("The email address contains an invalid local part or domain label.")
    email = f"{local}@{domain}"
    key_file = Path(key_file).resolve()
    source = key_file.read_bytes()
    if not source.lstrip().startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----") or b"PRIVATE KEY BLOCK" in source:
        raise ValueError("Provide an ASCII-armored PUBLIC key exported with gpg --armor --export.")

    data_file = root / "data/pgp.json"
    data = json.loads(data_file.read_text())
    if any(entry["email"].split("@")[1] != domain for entry in data["keys"]):
        raise ValueError("Direct WKD serves one email domain per site. Use a separate checkout for another domain.")

    with tempfile.TemporaryDirectory(prefix="personal-site-pgp-") as home:
        records = [line.split(":") for line in run_gpg(home, "--with-colons", "--show-keys", str(key_file)).decode().splitlines()]
        if any(row[0] in {"sec", "ssb"} for row in records):
            raise ValueError("Secret key material is not accepted. Export only the public key.")
        primary_keys = [row for row in records if row[0] == "pub"]
        if len(primary_keys) != 1:
            raise ValueError("The input must contain exactly one public primary key.")
        primary = primary_keys[0]
        if primary[1] in {"r", "e", "d", "i"}:
            raise ValueError("The supplied primary key is revoked, expired, disabled, or invalid.")
        fingerprint = next(row[9] for row in records if row[0] == "fpr")
        run_gpg(home, "--import", str(key_file))
        export_args = ["--export-options", "export-minimal,no-export-attributes"]
        armored = run_gpg(home, *export_args, "--armor", "--export", fingerprint)
        binary = run_gpg(home, *export_args, "--export-filter", f"keep-uid=mbox = {email}", "--export", fingerprint)
        # A filtered key without a matching, usable identity is not a WKD key.
        filtered_file = Path(home) / "filtered.gpg"
        filtered_file.write_bytes(binary)
        filtered = run_gpg(home, "--with-colons", "--show-keys", str(filtered_file)).decode()
        if not any(line.startswith("uid:") and line.split(":")[1] not in {"r", "e", "i"} for line in filtered.splitlines()):
            raise ValueError(f"The public key has no usable user ID for {email}.")

    hashed = wkd_hash(local)
    download = f"/keys/{fingerprint}.asc"
    entry = {
        "email": email,
        "fingerprint": fingerprint,
        "created": key_date(primary[5]),
        "expires": key_date(primary[6]),
        "download": download,
        "hash": hashed,
        "wkd": f"https://{domain}/.well-known/openpgpkey/hu/{hashed}?l={quote(local, safe='')}",
    }
    # Replace the active key for this mailbox; other mailboxes remain published.
    data["keys"] = sorted(
        [item for item in data["keys"] if item["email"] != email] + [entry],
        key=lambda item: item["email"],
    )
    download_path = root / "static" / download.lstrip("/")
    wkd_dir = root / ".wellknowndir/.well-known/openpgpkey"
    download_path.parent.mkdir(parents=True, exist_ok=True)
    (wkd_dir / "hu").mkdir(parents=True, exist_ok=True)
    download_path.write_bytes(armored)
    (wkd_dir / "hu" / hashed).write_bytes(binary)
    (wkd_dir / "policy").touch()
    data_file.write_text(json.dumps(data, indent=2) + "\n")
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Email address present on the public key")
    parser.add_argument("--key", type=Path, required=True, help="ASCII-armored public-key export")
    args = parser.parse_args()
    if not shutil.which("gpg"):
        parser.error("GnuPG (gpg) is required.")
    try:
        entry = prepare(args.email, args.key)
    except (OSError, ValueError, StopIteration) as error:
        print(f"Key preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"Prepared {entry['email']}\nFingerprint: {entry['fingerprint']}\nDownload: {entry['download']}\nWKD: {entry['wkd']}\nRun hugo and deploy the complete public/ directory to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
