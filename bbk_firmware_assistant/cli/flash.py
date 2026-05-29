from __future__ import annotations

import subprocess
from pathlib import Path

from ..services import flasher
from ._common import EXTRACTED_DIR, ask_confirm, ask_path, ask_select, error, success

PARTITION_GROUPS = ("BOOTLOADER", "CRITICAL", "SYSTEM", "MODEM")
MANUAL_PATH = "[ Enter path manually ]"


class Fastboot:
    """Thin fastboot wrapper. In dry-run mode it only prints commands."""

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run

    def run(self, *args: str) -> int:
        print(f"  $ fastboot {' '.join(args)}")
        if self.dry_run:
            return 0
        return subprocess.run(["fastboot", *args]).returncode

    def flash_or_retry(self, *args: str) -> bool:
        """Run a fastboot command; on failure ask the user to retry or stop."""
        while True:
            if self.run(*args) == 0:
                return True
            choice = ask_select(
                f"fastboot {' '.join(args[:2])} failed — retry or stop?",
                ["Retry", "Stop"],
            )
            if choice != "Retry":
                return False


def _select_firmware_dir() -> Path | None:
    """Let the user pick an extracted firmware dir or type a path."""
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    dirs = sorted(d for d in EXTRACTED_DIR.iterdir() if d.is_dir())

    def summary(d: Path) -> str:
        present = ", ".join(g for g in PARTITION_GROUPS if (d / g).is_dir())
        return f"{d.name}  ({present})"

    choices = [summary(d) for d in dirs] + [MANUAL_PATH]
    picked = ask_select(f"Select extracted firmware (in {EXTRACTED_DIR}):", choices)
    if not picked:
        return None

    if picked == MANUAL_PATH:
        path = ask_path("Path to directory with .img files:")
        img_dir = Path(path) if path else None
    else:
        img_dir = dirs[choices.index(picked)]

    if not img_dir or not img_dir.is_dir():
        if img_dir:
            error(f"Not a directory: {img_dir}")
        return None
    return img_dir


def flow_flash() -> None:
    if not flasher.fastboot_available():
        error("fastboot not found in PATH")
        return

    img_dir = _select_firmware_dir()
    if not img_dir:
        return

    groups = flasher.firmware_groups(img_dir)
    if sum(len(v) for v in groups.values()) == 0:
        error(f"No firmware files found in {img_dir} (expected {'/'.join(PARTITION_GROUPS)} subdirs)")
        return

    print()
    for group, files in groups.items():
        if files:
            shown = ", ".join(f.name for f in files[:4])
            print(f"  {group}: {shown}{'...' if len(files) > 4 else ''}")

    mode = ask_select("Mode:", ["Dry-run (show commands only)", "Flash (write to device)"])
    if not mode:
        return
    dry = mode.startswith("Dry")

    android_ver = ask_select("Android version on device:", ["13-15", "12", "10-11"])
    if not android_ver:
        return

    if not dry:
        print("\n  ⚠ WARNING: This will flash your device.")
        if not ask_confirm("Proceed with flashing?"):
            print("  Cancelled.")
            return

    _do_flash(img_dir, groups, dry_run=dry, android_ver=android_ver)


def _flash_both_slots(fb: Fastboot, files: list[Path]) -> bool:
    """Flash each file to both _a and _b slots. Returns False if the user aborted."""
    for f in files:
        for slot in ("_a", "_b"):
            if not fb.flash_or_retry("flash", f.stem + slot, str(f)):
                return False
    return True


def _do_flash(img_dir: Path, groups: dict, dry_run: bool = False, android_ver: str = "13-15") -> None:
    fb = Fastboot(dry_run)

    if dry_run:
        print("\n  (dry-run — no commands will be executed)\n")
    else:
        print("\n── Step 1: Enter fastboot (bootloader mode) ──")
        print("  Power off the device, then hold  Volume Down + Power  until")
        print("  the Fastboot screen appears, connect USB.")
        print("  The device must show  Fastboot Mode  (NOT userspace/fastbootd).")
        if not ask_confirm("Device is in fastboot (bootloader) mode and connected?"):
            print("  Cancelled.")
            return

    if groups.get("BOOTLOADER"):
        print("\n── BOOTLOADER ──")
        if not _flash_both_slots(fb, groups["BOOTLOADER"]):
            return

    print("\n── Rebooting into fastbootd ──")
    fb.run("reboot", "fastboot")
    if not dry_run:
        if not ask_confirm("Device is in fastbootd (userspace fastboot) and connected?"):
            print("  Cancelled.")
            return

    if android_ver == "10-11":
        print("\n── Android 10-11 cleanup ──")
        fb.run("delete-logical-partition", "my_bigball-cow")
        fb.run("delete-logical-partition", "my_bigball")

    if groups.get("CRITICAL"):
        print("\n── CRITICAL ──")
        if not _flash_both_slots(fb, groups["CRITICAL"]):
            return

    sys_files = groups.get("SYSTEM", [])
    if sys_files:
        print("\n── SYSTEM ──")
        for f in sys_files:
            for slot in ("_a", "_b"):
                fb.run("delete-logical-partition", f"{f.stem}{slot}-cow")
                fb.run("delete-logical-partition", f"{f.stem}{slot}")
                fb.run("create-logical-partition", f"{f.stem}{slot}", "0")
        for f in sys_files:
            if not fb.flash_or_retry("flash", f.stem, str(f)):
                return

    if not dry_run:
        if ask_select("Did you see any errors?", ["No errors — continue", "Stop"]) == "Stop":
            print("  Stopped.")
            return

    modem_files = groups.get("MODEM", [])
    modem = next((f for f in modem_files if f.name == "modem.img"), None)
    if modem:
        print("\n── Rebooting to fastboot (bootloader mode) for modem ──")
        fb.run("reboot", "bootloader")
        if not dry_run:
            ask_confirm("Device is back in fastboot (bootloader) mode and connected?")
        print("\n── MODEM ──")
        for slot in ("modem_a", "modem_b"):
            if not fb.flash_or_retry("flash", slot, str(modem)):
                return

    print("\n── Rebooting ──")
    if dry_run:
        fb.run("reboot")
        success("Dry-run complete — no changes were made.")
        return

    action = ask_select(
        "Post-flash action:",
        ["Reboot to system", "Wipe data and reboot", "Do not reboot"],
    )
    if action == "Wipe data and reboot":
        fb.flash_or_retry("erase", "userdata")
        fb.run("reboot")
    elif action == "Reboot to system":
        fb.run("reboot")
    success("Flash complete!")