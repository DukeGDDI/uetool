import keyring
import pytest
from keyring.backend import KeyringBackend

from ui import secrets


class Mem(KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        self.d.pop((s, u), None)


@pytest.fixture(autouse=True)
def backend():
    old = keyring.get_keyring()
    keyring.set_keyring(Mem())
    yield
    keyring.set_keyring(old)


def test_roundtrip_and_env():
    secrets.set("steam", "bob", "pw1")
    secrets.set("apple", "a@b.c", "pw2")
    assert secrets.has("steam", "bob") and not secrets.has("steam", "alice")
    assert secrets.env_for("bob", "a@b.c") == {
        "UETOOL_STEAM_PASSWORD": "pw1", "UETOOL_APPLE_APP_PASSWORD": "pw2"}
    assert secrets.env_for("alice", "") == {}
    secrets.delete("steam", "bob")
    assert not secrets.has("steam", "bob")
