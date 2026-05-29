"""
Python port of OplusUpdater (github.com/Houvven/OplusUpdater).
Queries the Oplus/ColorOS OTA update API.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .pubkeys import SERVER_CONFIGS

REGION_TO_NV_ID: dict[str, str] = {
    "IN": "00011011",
    "EU": "01000100",
    "GLO": "10100111",
    "CN": "10010111",
    "TR": "01010001",
    "RU": "00110111",
    "MEA": "10100110",
    "SA": "10000011",
    "TH": "00111001",
    "LATAM": "10011010",
    "BR": "10011110",
    "TW": "00011010",
    "ID": "00110033",
    "MY": "00111000",
    "PH": "00111110",
    "GB": "10001010",
    "SG": "00101100",
    "VN": "00111100",
    "OCA": "10100101",
}

@dataclass
class QueryArgs:
    product_model: str  # base model (e.g. "CPH2793") — used to build OtaVersion
    product_name: str = ""  # --model header (e.g. "CPH2793IN"); falls back to product_model
    ota_version: str = "A"  # channel letter (e.g. "A") — combined into OtaVersion
    region: str = ""  # device region (e.g. "IN", "GLO") — maps to NvCarrier
    carrier: str = ""  # explicit --carrier override (bypasses region lookup)
    server: int = 1  # 0=SG, 1=CN, 2=IN, 3=EU
    mode: int = 0  # 0=stable, 1=testing
    gray: int = 0  # 0=normal, 1=gray/staged
    req_mode: str = "manual"  # manual / taste / server_auto / client_auto
    imei: str = ""
    proxy: str = ""

@dataclass
class OtaLink:
    url: str
    filename: str
    label: str = ""  # human-readable hint, e.g. "direct" or "api-gated"

@dataclass
class QueryResult:
    response_code: int
    err_msg: str
    body: dict
    links: list[OtaLink] = field(default_factory=list)
    raw_output: str = ""

def _random_iv() -> bytes:
    return os.urandom(16)

def _random_key() -> bytes:
    return os.urandom(32)

def _protected_key_version() -> str:
    return str(time.time_ns() + 86_400_000_000_000)

def _encrypt_key_rsa(key: bytes, pub_key_pem: bytes) -> str:
    """RSA-OAEP encrypt base64(key) with server public key."""
    pub_key = serialization.load_pem_public_key(pub_key_pem)
    plaintext = base64.b64encode(key)
    ciphertext = pub_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode()

def _aes_ctr_encrypt(data: bytes, key: bytes, iv: bytes) -> str:
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    enc = cipher.encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode()

def _aes_ctr_decrypt(cipher_b64: str, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    dec = cipher.decryptor()
    return dec.update(base64.b64decode(cipher_b64)) + dec.finalize()

def _device_id(imei: str) -> str:
    if not imei.strip():
        return "0" * 64
    return hashlib.sha256(imei.encode()).hexdigest().upper()

def build_ota_version(product_model: str, ota_channel: str) -> str:
    return f"{product_model}_11.{ota_channel}.01_0001_100001010000"

def url_filename(url: str) -> str:
    """Derive a filesystem-safe filename from a URL."""
    parsed = urlparse(url)
    path_part = parsed.path.rsplit("/", 1)[-1]
    # Use path filename only if it looks like a real file (has an extension)
    if path_part and "." in path_part:
        return path_part
    # For query-param URLs (e.g. /downloadCheck?id=...&...), use the id param
    params = parse_qs(parsed.query)
    id_val = (params.get("id") or params.get("g") or [""])[0]
    return f"{id_val}.zip" if id_val else "firmware.zip"

def _extract_links(data: object) -> list[OtaLink]:
    """Walk JSON object and collect HTTP URLs, preferring manualUrl over API-gated URLs."""
    direct: list[OtaLink] = []
    gated: list[OtaLink] = []
    seen: set[str] = set()

    def add(url: str, key: str = "") -> None:
        url = url.rstrip("\"')")
        if url in seen:
            return
        seen.add(url)
        filename = url_filename(url)
        is_gated = "/downloadCheck" in url or "/check" in url
        if key == "manualUrl" or not is_gated:
            direct.append(OtaLink(url=url, filename=filename, label="direct"))
        else:
            gated.append(OtaLink(url=url, filename=filename, label="api-gated"))

    def walk(node: object, key: str = "") -> None:
        if isinstance(node, str):
            if node.startswith("http://") or node.startswith("https://"):
                add(node, key)
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)

    walk(data)

    links = direct + gated

    if not links:
        # fallback: regex over raw string
        raw = json.dumps(data) if not isinstance(data, str) else data
        for m in re.finditer(r"https?://[^\s\"']+", raw, re.IGNORECASE):
            add(m.group(0))
        links = direct + gated

    return links

async def query_update(args: QueryArgs) -> QueryResult:
    cfg = SERVER_CONFIGS.get(args.server, SERVER_CONFIGS[1])

    ota_ver = build_ota_version(args.product_model, args.ota_version)
    model = args.product_name or args.product_model
    carrier = args.carrier or REGION_TO_NV_ID.get(args.region, cfg["carrier_id"])
    device_id = _device_id(args.imei)

    iv = _random_iv()
    key = _random_key()
    protected_key = _encrypt_key_rsa(key, cfg["public_key"])

    protected_key_header = json.dumps({
        "SCENE_1": {
            "protectedKey": protected_key,
            "version": _protected_key_version(),
            "negotiationVersion": cfg["pubkey_version"],
        }
    })

    body_plain = json.dumps({
        "mode": args.mode,
        "time": int(time.time() * 1000),
        "isRooted": "0",
        "isLocked": True,
        "type": "1",
        "deviceId": device_id,
        **({"gray": args.gray} if args.gray else {}),
    }).encode()

    request_body = json.dumps({
        "cipher": _aes_ctr_encrypt(body_plain, key, iv),
        "iv": base64.b64encode(iv).decode(),
    })

    headers = {
        "language": cfg["language"],
        "androidVersion": "unknown",
        "colorOSVersion": "unknown",
        "otaVersion": ota_ver,
        "model": model,
        "mode": args.req_mode,
        "nvCarrier": carrier,
        "version": cfg["version"],
        "deviceId": device_id,
        "Content-Type": "application/json; charset=utf-8",
        "protectedKey": protected_key_header,
    }

    url = f"https://{cfg['host']}/update/v5"
    payload = {"params": request_body}

    proxy = args.proxy.strip() or None
    async with httpx.AsyncClient(
        proxy=proxy,
        timeout=30.0,
    ) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()

    outer: dict = resp.json()
    response_code: int = outer.get("responseCode", -1)
    err_msg: str = outer.get("errMsg", "")

    body_raw = outer.get("body")
    body_dict: dict = {}
    if isinstance(body_raw, str):
        try:
            enc = json.loads(body_raw)
            body_iv = base64.b64decode(enc["iv"])
            decrypted = _aes_ctr_decrypt(enc["cipher"], key, body_iv)
            body_dict = json.loads(decrypted)
        except Exception:
            body_dict = {}
    elif isinstance(body_raw, dict):
        body_dict = body_raw

    links = _extract_links(body_dict)
    raw_output = json.dumps({"responseCode": response_code, "errMsg": err_msg, "body": body_dict}, indent=2)

    return QueryResult(
        response_code=response_code,
        err_msg=err_msg,
        body=body_dict,
        links=links,
        raw_output=raw_output,
    )
