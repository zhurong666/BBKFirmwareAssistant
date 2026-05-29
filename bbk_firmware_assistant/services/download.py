"""Download service — wraps wget / curl / aria2c."""
from __future__ import annotations

import shutil
from pathlib import Path

DOWNLOADERS = [
    "aria2c",
    "wget",
    "curl",
]

def available_downloaders() -> list[str]:
    return [d for d in DOWNLOADERS if shutil.which(d)]

def _ota_headers(url: str) -> dict[str, str]:
    if "downloadCheck" in url:
        return {
            "User-Agent": "okhttp/3.14.9",
            "userId": "oplus-ota|16000015",
        }
    return {}

def build_command(downloader: str, url: str, output_path: Path) -> list[str]:
    headers = _ota_headers(url)
    match downloader:
        case "wget":
            hdr_args = [f"--header={k}: {v}" for k, v in headers.items()]
            return ["wget", "-O", str(output_path), "--show-progress", *hdr_args, url]
        case "curl":
            hdr_args = [arg for k, v in headers.items() for arg in ("-H", f"{k}: {v}")]
            return ["curl", "-L", "-o", str(output_path), "--progress-bar", *hdr_args, url]
        case "aria2c":
            hdr_args = [f"--header={k}: {v}" for k, v in headers.items()]
            return [
                "aria2c",
                "--dir", str(output_path.parent),
                "--out", output_path.name,
                "--continue=true",
                "--max-connection-per-server=8",
                "--split=8",
                *hdr_args,
                url,
            ]
        case _:
            raise ValueError(f"Unknown downloader: {downloader}")
