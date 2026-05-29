"""OTA extraction service."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

_CLASSIFY_GROUPS: dict[str, tuple[str, ...]] = {
    "BOOTLOADER": (
        "vendor_boot", "vbmeta", "init_boot", "recovery", "boot",
    ),
    "CRITICAL": (
        "abl", "aop_config", "aop", "bluetooth", "cpucp", "devcfg", "dsp", "dtbo",
        "engineering_cdt", "featenabler", "hyp", "imagefv", "keymaster", "oplus_sec",
        "oplusstanvbk", "qupfw", "shrm", "splash", "tz", "uefi", "uefisecapp",
        "apusys", "audio_dsp", "ccu", "cdt_engineering", "dpm", "gpueb", "gz", "lk",
        "mcf_ota", "mcump", "md1img", "mvpu_algo", "pi_img", "preloader_raw", "scp",
        "spmfw", "sspm", "tee",
        "multiimgoem", "qweslicstore", "vm-bootsys", "xbl_config", "xbl_ramdisk", "xbl",
    ),
    "SYSTEM": (
        "my_bigball", "my_carrier", "my_company", "my_engineering", "my_heytap",
        "my_manifest", "my_preload", "my_product", "my_region", "my_stock",
        "odm_dlkm", "odm", "product", "system_dlkm", "system_ext", "system",
        "vendor_dlkm", "vendor",
    ),
    "MODEM": (
        "modem",
    ),
}

def read_ota_metadata(zip_path: Path) -> dict[str, str]:
    """Read META-INF/com/android/metadata from an OTA ZIP. Returns key→value dict."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            meta_name = next(
                (n for n in zf.namelist() if n.endswith("META-INF/com/android/metadata")),
                None,
            )
            if not meta_name:
                return {}
            text = zf.read(meta_name).decode(errors="replace")
        result: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
        return result
    except Exception:
        return {}


def find_dumper() -> str | None:
    for c in ("payload-dumper-go", "payload_dumper_go", "./payload-dumper-go"):
        if shutil.which(c):
            return c
    return None


def _classify(filename: str) -> str:
    for group, prefixes in _CLASSIFY_GROUPS.items():
        if any(filename.startswith(p) for p in prefixes):
            return group
    return "CRITICAL"


def organize_firmware(img_dir: Path) -> dict[str, int]:
    """Move flat .img files into BOOTLOADER/CRITICAL/SYSTEM/MODEM subdirs."""
    imgs = [f for f in img_dir.iterdir() if f.is_file() and f.suffix.lower() == ".img"]
    counts: dict[str, int] = {}
    for f in imgs:
        group = _classify(f.name)
        dest = img_dir / group
        dest.mkdir(exist_ok=True)
        f.rename(dest / f.name)
        counts[group] = counts.get(group, 0) + 1
    return counts
