from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

@dataclass
class DeviceModel:
    region: str
    product_model: str  # e.g. "CPH2793"
    product_name: str  # e.g. "CPH2793IN"
    ota_version: str  # e.g. "A"
    mode: int  # 0=stable, 1=testing
    server: int  # 0=SG, 1=CN, 2=IN, 3=EU
    gray: int  # 0 or 1
    req_mode: str  # "manual", "taste", etc.
    imei: str = ""
    proxy: str = ""
    full_model_name: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceModel":
        return cls(
            region=d.get("Region", ""),
            product_model=d.get("ProductModel", ""),
            product_name=d.get("ProductName", ""),
            ota_version=d.get("OtaVersion", "A"),
            mode=d.get("Mode", 0),
            server=d.get("Server", 1),
            gray=d.get("Gray", 0),
            req_mode=d.get("ReqMode", "manual"),
            imei=d.get("Imei", ""),
            proxy=d.get("Proxy", ""),
            full_model_name=d.get("FullModelName"),
        )

    @property
    def display_name(self) -> str:
        name = self.full_model_name or self.product_name
        if self.region:
            return f"{name} [{self.region}]"
        return name

@dataclass
class DeviceGroup:
    title: str
    models: list[DeviceModel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceGroup":
        return cls(
            title=d.get("DeviceTitle", "Unknown"),
            models=[DeviceModel.from_dict(m) for m in d.get("Models", [])],
        )

def load_vendor(vendor: str) -> list[DeviceGroup]:
    path = DATA_DIR / f"ota_{vendor.lower()}.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [DeviceGroup.from_dict(g) for g in data]
    except Exception:
        return []
