"""Validate Plugin Hub release identity before packaging or promotion."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def validate(manifest: dict, device: dict, tag: str) -> None:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"invalid release tag: {tag}")
    version = tag[1:]
    if manifest.get("name") != "pluginhub":
        raise ValueError("manifest plugin ID must be pluginhub")
    new_release = tuple(map(int, version.split("."))) >= (0, 1, 8)
    for name, metadata in (("manifest.json", manifest), ("device.json", device)):
        # Older device.json files did not carry a version; keep published
        # historical releases available for manual repackaging.
        if metadata.get("version") != version and not (
            name == "device.json" and not new_release and metadata.get("version") is None
        ):
            raise ValueError(f"{name} version must match release tag {tag}")
        if new_release and metadata.get("title") != "Plugin Hub":
            raise ValueError(f"{name} title must be 'Plugin Hub' (no version suffix)")


def read_file(name: str, tag: str | None) -> dict:
    data = (subprocess.check_output(["git", "show", f"{tag}:{name}"], text=True)
            if tag else Path(name).read_text(encoding="utf-8"))
    return json.loads(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v0.1.8")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--worktree", action="store_true", help="validate working files before tagging")
    source.add_argument("--ref", help="validate another Git ref, e.g. origin/main")
    args = parser.parse_args()
    ref = None if args.worktree else (args.ref or args.tag)
    try:
        validate(read_file("manifest.json", ref),
                 read_file("device.json", ref),
                 args.tag)
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Release metadata validation failed: {exc}\n")
    print(f"PASS: {args.tag} manifests agree on version and the required title")


if __name__ == "__main__":
    main()
