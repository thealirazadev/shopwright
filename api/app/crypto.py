from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


class TokenCipher:
    """Symmetric encryption for third-party credentials at rest."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode()


@lru_cache
def get_cipher() -> TokenCipher:
    key = get_settings().token_encryption_key
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return TokenCipher(key)
