from __future__ import annotations

import asyncio
from pathlib import Path

from ..api.oplus_updater import OtaLink, QueryArgs, QueryResult, build_ota_version, query_update, url_filename
from ..models.device import DeviceModel, load_vendor
from ..services.download import available_downloaders, build_command
from ..services.extractor import read_ota_metadata
from ._common import DOWNLOADS_DIR, ask_select, ask_text, error, run_cmd, success


def _query_and_download(model: DeviceModel) -> None:
    ota_ver = build_ota_version(model.product_model, model.ota_version)
    print(f"\n  Querying OTA server for {ota_ver} (server={model.server})...")

    args = QueryArgs(
        product_model=model.product_model,
        product_name=model.product_name,
        ota_version=model.ota_version,
        region=model.region,
        server=model.server,
        mode=model.mode,
        gray=model.gray,
        req_mode=model.req_mode,
        imei=model.imei,
        proxy=model.proxy,
    )

    try:
        result: QueryResult = asyncio.run(query_update(args))
    except Exception as e:
        error(f"API error: {e}")
        return

    if result.response_code != 200:
        error(f"Server returned code {result.response_code}: {result.err_msg}")

    if not result.links:
        error("No download links found in the response.")
        print("\nRaw response:")
        print(result.raw_output)
        return

    link = result.links[0]
    if len(result.links) > 1:
        print(f"  Using {link.label} link ({len(result.links)} available)")
    _download_link(link)


def _download_link(link: OtaLink) -> None:
    """Pick a downloader, download the link, then rename the ZIP by its metadata version_name."""
    print(f"\n  URL: {link.url[:80]}{'...' if len(link.url) > 80 else ''}")

    available = available_downloaders()
    if not available:
        error("No download tool found. Install wget, curl, or aria2c.")
        return

    downloader = ask_select("Download method:", available)
    if not downloader:
        return

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOWNLOADS_DIR / link.filename
    print(f"  Saving to: {out_path}\n")

    rc = run_cmd(*build_command(downloader, link.url, out_path))
    if rc != 0:
        error(f"Download failed (exit {rc})")
        return

    final_path = _rename_by_metadata(out_path)
    success(f"Download complete: {final_path}")


def _rename_by_metadata(zip_path: Path) -> Path:
    """Rename a downloaded ZIP to its version_name from OTA metadata. Returns the final path."""
    if zip_path.suffix.lower() != ".zip" or not zip_path.exists():
        return zip_path
    version_name = read_ota_metadata(zip_path).get("version_name", "").strip()
    if not version_name:
        return zip_path
    new_path = zip_path.parent / f"{version_name}.zip"
    if new_path == zip_path:
        return zip_path
    if not new_path.exists():
        zip_path.rename(new_path)
    return new_path


def _download_custom() -> None:
    url = ask_text("Enter URL:")
    if not url:
        return
    _download_link(OtaLink(url=url, filename=url_filename(url)))


def flow_download() -> None:
    vendor = ask_select("Vendor:", ["OnePlus", "OPPO", "Realme", "Custom link"])
    if not vendor:
        return

    if vendor == "Custom link":
        _download_custom()
        return

    groups = load_vendor(vendor)
    if not groups:
        error(f"No devices found for {vendor}. Check bbk_assistant/data/ota_{vendor}.json")
        return

    group_name = ask_select("Device:", [g.title for g in groups])
    if not group_name:
        return
    group = next(g for g in groups if g.title == group_name)

    if not group.models:
        error("No revisions in this group.")
        return

    model_name = ask_select("Revision:", [m.display_name for m in group.models])
    if not model_name:
        return
    model = next(m for m in group.models if m.display_name == model_name)

    _query_and_download(model)