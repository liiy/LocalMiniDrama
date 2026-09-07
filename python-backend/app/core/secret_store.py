"""应用敏感信息加密存储。

AI Key 使用 Fernet 对称加密后再写入数据库。生产环境应通过 `LMD_MASTER_KEY`
统一注入主密钥；本地单实例开发可以使用数据目录中自动生成的密钥文件。
"""
from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SECRET_PREFIX = "enc:v1:"


def _default_key_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / ".lmd_master_key"


def _normalize_key(raw: str) -> bytes:
    """兼容标准 Fernet Key 和普通高强度口令。"""
    encoded = raw.strip().encode("utf-8")
    try:
        Fernet(encoded)
        return encoded
    except (TypeError, ValueError):
        # 部署平台若只能注入口令，则稳定派生 32 字节密钥；推荐直接使用 Fernet Key。
        return base64.urlsafe_b64encode(hashlib.sha256(encoded).digest())


def _load_or_create_local_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes().strip()

    generated = Fernet.generate_key()
    try:
        # 独占创建防止多线程同时启动时互相覆盖密钥。
        with path.open("xb") as stream:
            stream.write(generated)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return generated
    except FileExistsError:
        return path.read_bytes().strip()


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    try:
        from app.core.config import load_config
        cfg = load_config()
        security = cfg.get("security", {})
        config_key = security.get("master_key")
        config_file = security.get("master_key_file")
    except Exception:
        config_key = None
        config_file = None

    env_key = os.environ.get("LMD_MASTER_KEY") or config_key
    if env_key:
        return Fernet(_normalize_key(env_key))

    raw_file = os.environ.get("LMD_MASTER_KEY_FILE") or config_file
    key_path = Path(raw_file) if raw_file else _default_key_path()
    if not key_path.is_absolute() and not key_path.exists():
        for alt in (
            Path(__file__).resolve().parents[2] / key_path,
            Path(__file__).resolve().parents[3] / key_path,
        ):
            if alt.exists():
                key_path = alt
                break
    return Fernet(_normalize_key(_load_or_create_local_key(key_path).decode("utf-8")))


def is_encrypted_secret(value: object) -> bool:
    return str(value or "").startswith(SECRET_PREFIX)


def encrypt_secret(value: object) -> str:
    """加密敏感字符串；空值和已经加密的值保持幂等。"""
    plain = str(value or "")
    if not plain or is_encrypted_secret(plain):
        return plain
    token = _cipher().encrypt(plain.encode("utf-8")).decode("ascii")
    return SECRET_PREFIX + token


def decrypt_secret(value: object) -> str:
    """解密数据库敏感值，同时兼容待迁移的历史明文。"""
    stored = str(value or "")
    if not stored or not is_encrypted_secret(stored):
        return stored
    try:
        return _cipher().decrypt(stored[len(SECRET_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as err:
        raise ValueError("AI 配置密钥无法解密，请检查 LMD_MASTER_KEY 是否正确") from err


def reset_secret_cipher_cache() -> None:
    """仅供测试或进程内密钥切换场景清理缓存。"""
    _cipher.cache_clear()
