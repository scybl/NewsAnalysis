from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET_DIR = PROJECT_ROOT / "local_data" / "secure"


SECRET_ENV_MAP: dict[str, tuple[str, ...]] = {
    "tushare.api_token": ("TUSHARE_API", "TUSHARE_TOKEN"),
    "web.admin_username": ("STOCK_WEB_USER",),
    "web.admin_password": ("STOCK_WEB_PASSWORD", "STOCK_WEB_PASS"),
    "web.admin_readonly_username": ("ADMIN_READONLY_USER", "STOCK_ADMIN_READONLY_USER"),
    "web.admin_readonly_password": ("ADMIN_READONLY_PASSWORD", "STOCK_ADMIN_READONLY_PASSWORD"),
    "web.admin_totp_secret": ("STOCK_WEB_ADMIN_TOTP_SECRET",),
    "web.session_secret": ("STOCK_WEB_SESSION_SECRET",),
    "web.key_encryption_secret": ("STOCK_WEB_KEY_ENCRYPTION_SECRET",),
    "mongo.uri": ("MONGODB_URI", "MONGO_URI"),
    "mongo.user": ("MONGO_USER",),
    "mongo.password": ("MONGO_PASSWORD",),
    "mongo.password_uri": ("MONGO_PASSWORD_URI",),
    "proxy.username": ("PROXY_USERNAME",),
    "proxy.password": ("PROXY_PASSWORD",),
    "ssh.username": ("SSH_USER",),
    "ssh.key_path": ("SSH_KEY_PATH",),
    "ssh.key_passphrase": ("SSH_KEY_PASSPHRASE",),
}

ENV_SECRET_ALIASES = {
    env_name: secret_name
    for secret_name, env_names in SECRET_ENV_MAP.items()
    for env_name in env_names
}


@dataclass(frozen=True)
class SecretState:
    configured: bool
    updated_at: str = ""


class SecretStore:
    def __init__(self, root: Path = DEFAULT_SECRET_DIR):
        self.root = root
        self.key_path = root / "master.key"
        self.data_path = root / "secrets.json.enc"
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._fernet = Fernet(self._load_or_create_master_key())

    def get(self, name: str, default: str = "") -> str:
        item = self._read().get("secrets", {}).get(name) or {}
        ciphertext = item.get("ciphertext")
        if not ciphertext:
            return default
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(f"密钥 {name} 解密失败，请检查本地 master.key 是否匹配。") from exc

    def get_first(self, names: Iterable[str], default: str = "") -> str:
        for name in names:
            value = self.get(name)
            if value:
                return value
        return default

    def set(self, name: str, value: str, *, updated_by: str = "local") -> None:
        value = str(value or "")
        if not value:
            raise ValueError("密钥值不能为空。")
        data = self._read()
        secrets = data.setdefault("secrets", {})
        secrets[name] = {
            "ciphertext": self._fernet.encrypt(value.encode("utf-8")).decode("utf-8"),
            "updated_at": self._timestamp(),
            "updated_by": updated_by,
        }
        self._write(data)

    def delete(self, name: str) -> bool:
        data = self._read()
        existed = name in data.setdefault("secrets", {})
        data["secrets"].pop(name, None)
        if existed:
            self._write(data)
        return existed

    def state(self, name: str) -> SecretState:
        item = self._read().get("secrets", {}).get(name) or {}
        return SecretState(configured=bool(item.get("ciphertext")), updated_at=item.get("updated_at", ""))

    def list_states(self) -> dict[str, SecretState]:
        data = self._read()
        return {
            name: SecretState(configured=bool(item.get("ciphertext")), updated_at=item.get("updated_at", ""))
            for name, item in sorted((data.get("secrets") or {}).items())
        }

    def migrate_from_env(self, environ: dict[str, str] | None = None) -> list[str]:
        env = environ or os.environ
        migrated: list[str] = []
        for secret_name, env_names in SECRET_ENV_MAP.items():
            if self.state(secret_name).configured:
                continue
            for env_name in env_names:
                value = env.get(env_name)
                if value:
                    self.set(secret_name, value, updated_by=f"env:{env_name}")
                    migrated.append(secret_name)
                    break
        return migrated

    def master_secret(self) -> str:
        key = self._load_or_create_master_key()
        return hashlib.sha256(key).hexdigest()

    def _load_or_create_master_key(self) -> bytes:
        if self.key_path.exists():
            key = self.key_path.read_text(encoding="utf-8").strip().encode("utf-8")
            os.chmod(self.key_path, 0o600)
            return key
        key = Fernet.generate_key()
        self.key_path.write_text(key.decode("utf-8"), encoding="utf-8")
        os.chmod(self.key_path, 0o600)
        return key

    def _read(self) -> dict:
        if not self.data_path.exists():
            return {"version": 1, "secrets": {}}
        ciphertext = self.data_path.read_bytes()
        if not ciphertext:
            return {"version": 1, "secrets": {}}
        try:
            raw = self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("加密密钥库解密失败，请检查 local_data/secure/master.key。") from exc
        data = json.loads(raw)
        data.setdefault("version", 1)
        data.setdefault("secrets", {})
        return data

    def _write(self, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        tmp_path = self.data_path.with_name(f".{self.data_path.name}.tmp")
        tmp_path.write_bytes(self._fernet.encrypt(raw))
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.data_path)
        os.chmod(self.data_path, 0o600)

    def _timestamp(self) -> str:
        from .utils import timestamp

        return timestamp()


def get_secret_store() -> SecretStore:
    return SecretStore()


def secret_value(name: str, env_names: Iterable[str] = (), default: str = "") -> str:
    store = get_secret_store()
    value = store.get(name)
    if value:
        return value
    for env_name in env_names:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value
    return default


def secret_env_value(env_name: str, default: str = "") -> str:
    secret_name = ENV_SECRET_ALIASES.get(env_name)
    if secret_name:
        value = get_secret_store().get(secret_name)
        if value:
            return value
    return os.getenv(env_name, default)


def urlsafe_password(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)
