"""Acquire an immutable author snapshot; retain only inert CSV/document files."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

REPOSITORY = "pvtryan1024/2025_Cybersickness_dataset"
PINNED_COMMIT = "b8285924017f0f128cec98407914ced1073983e8"

def acquire(output: Path, commit=PINNED_COMMIT):
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{commit}"
    request = urllib.request.Request(url, headers={"User-Agent": "CybersicknessResearchAudit/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            relative = Path(*Path(info.filename).parts[1:])
            if info.is_dir() or relative.is_absolute() or ".." in relative.parts:
                continue
            if relative.parts[:1] == ("Dataset",) and relative.suffix.lower() == ".csv":
                target = output / relative
            elif str(relative) in ("LICENSE", "README.md", "readme.md"):
                # The upstream has README.md and readme.md: preserve both on Windows.
                target = output / ("README_upper.md" if str(relative) == "README.md" else str(relative))
            else:
                continue
            data = archive.read(info)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise ValueError(f"Refusing to replace a different snapshot: {target}")
            target.write_bytes(data)
            records.append({"upstream_path": relative.as_posix(), "local_path": target.relative_to(output).as_posix(),
                            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"repository": f"https://github.com/{REPOSITORY}", "commit": commit,
                "archive_url": url, "archive_sha256": hashlib.sha256(payload).hexdigest(),
                "license_file": "LICENSE", "files": records, "csv_files": sum(r["upstream_path"].endswith(".csv") for r in records)}
    (output / "acquisition_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"commit": commit, "csv_files": manifest["csv_files"], "bytes": len(payload)}), flush=True)
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/ryu2026")
    parser.add_argument("--commit", default=PINNED_COMMIT)
    arguments = parser.parse_args()
    acquire(Path(arguments.output), arguments.commit)
