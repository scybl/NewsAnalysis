from __future__ import annotations

import base64
import hmac
import hashlib
import secrets
import struct
import time
import urllib.parse


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def normalize_totp_secret(secret: str) -> str:
    return "".join(str(secret or "").strip().replace(" ", "").split("-")).upper()


def totp_code(secret: str, *, for_time: int | None = None, interval: int = 30, digits: int = 6) -> str:
    normalized = normalize_totp_secret(secret)
    padded = normalized + "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int((for_time if for_time is not None else time.time()) // interval)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def verify_totp(secret: str, code: str, *, interval: int = 30, digits: int = 6, window: int = 1) -> bool:
    candidate = "".join(ch for ch in str(code or "").strip() if ch.isdigit())
    if len(candidate) != digits:
        return False
    now = int(time.time())
    for step in range(-window, window + 1):
        expected = totp_code(secret, for_time=now + step * interval, interval=interval, digits=digits)
        if hmac.compare_digest(candidate, expected):
            return True
    return False


def otpauth_uri(secret: str, *, account: str, issuer: str = "ValueScope DataHub") -> str:
    label = f"{issuer}:{account}"
    params = urllib.parse.urlencode(
        {
            "secret": normalize_totp_secret(secret),
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    return f"otpauth://totp/{urllib.parse.quote(label)}?{params}"
