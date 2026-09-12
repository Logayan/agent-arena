from __future__ import annotations

import base64
import binascii
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStorageError(RuntimeError):
    """Raised when a persisted credential cannot be encrypted or decrypted."""


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _fernet(key_path: Path) -> Fernet:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key = key_path.read_bytes().strip()
    except FileNotFoundError:
        generated = Fernet.generate_key()
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = key_path.read_bytes().strip()
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(generated)
            key = generated
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise SecretStorageError("secret_key_invalid") from exc


def _protect_with_dpapi(value: str) -> str:
    input_blob, input_buffer = _blob(value.encode("utf-8"))
    output_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob), "Jianghu Online", None, None, None, 0, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def _unprotect_with_dpapi(value: str) -> str:
    input_blob, input_buffer = _blob(base64.b64decode(value))
    output_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def protect_secret(value: str, *, key_path: str | Path | None = None) -> str:
    """Encrypt new values with an application key that survives service restarts."""
    if key_path is None:
        if os.name != "nt":
            raise SecretStorageError("secure_secret_storage_not_available")
        return _protect_with_dpapi(value)
    encrypted = _fernet(Path(key_path)).encrypt(value.encode("utf-8")).decode("ascii")
    return f"fernet:v1:{encrypted}"


def unprotect_secret(value: str, *, key_path: str | Path | None = None) -> str:
    if value.startswith("fernet:v1:"):
        if key_path is None:
            raise SecretStorageError("secret_key_path_required")
        try:
            decrypted = _fernet(Path(key_path)).decrypt(value.removeprefix("fernet:v1:").encode("ascii"))
            return decrypted.decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise SecretStorageError("model_token_cannot_be_decrypted") from exc
    if os.name != "nt":
        raise SecretStorageError("legacy_model_token_cannot_be_decrypted")
    try:
        return _unprotect_with_dpapi(value)
    except (OSError, ValueError, binascii.Error) as exc:
        raise SecretStorageError("legacy_model_token_cannot_be_decrypted") from exc
