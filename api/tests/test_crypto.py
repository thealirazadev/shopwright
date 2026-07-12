import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.crypto import TokenCipher


def test_round_trip() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    token = "shpat_0123456789abcdef"
    ciphertext = cipher.encrypt(token)
    assert ciphertext != token.encode()
    assert cipher.decrypt(ciphertext) == token


def test_wrong_key_cannot_decrypt() -> None:
    ciphertext = TokenCipher(Fernet.generate_key().decode()).encrypt("secret")
    other = TokenCipher(Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        other.decrypt(ciphertext)
