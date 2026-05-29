"""Fastboot flash service"""
from __future__ import annotations

import shutil
from pathlib import Path

def fastboot_available() -> bool:
    return bool(shutil.which("fastboot"))

def firmware_groups(img_dir: Path) -> dict[str, list[Path]]:
    """Return files per group present in img_dir. Empty list = group absent."""
    groups: dict[str, list[Path]] = {}
    for group in ("BOOTLOADER", "CRITICAL", "SYSTEM", "MODEM"):
        d = img_dir / group
        if d.is_dir():
            files = sorted(d.iterdir())
            groups[group] = [f for f in files if f.is_file()]
        else:
            groups[group] = []
    return groups
