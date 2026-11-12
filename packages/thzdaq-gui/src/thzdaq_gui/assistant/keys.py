"""The keys of the providers: in the keyring of the system (Windows Credential
Locker, macOS Keychain, Secret Service), by the provider's name, never in the
settings. Where the system keeps none, a key lives only while the program
runs, and kept() says so."""

from typing import Dict, Optional

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "ThzDAQ assistant"


class Keys:
    def __init__(self):
        self._here: Dict[str, str] = {}  # where the system keeps none
        self.problem: Optional[str] = None  # why the system keeps none

    def kept(self) -> bool:
        """Keys outlive the program."""
        return self.problem is None

    def get(self, provider: str) -> Optional[str]:
        if provider in self._here:
            return self._here[provider]
        try:
            return keyring.get_password(SERVICE, provider)
        except KeyringError as e:
            self.problem = str(e)
            return None

    def set(self, provider: str, key: str) -> None:
        """Keep the key (an empty one forgets it)."""
        if not key:
            self.forget(provider)
            return
        try:
            keyring.set_password(SERVICE, provider, key)
            self._here.pop(provider, None)
        except KeyringError as e:
            self.problem = str(e)
            self._here[provider] = key

    def forget(self, provider: str) -> None:
        self._here.pop(provider, None)
        try:
            keyring.delete_password(SERVICE, provider)
        except PasswordDeleteError:
            pass  # none was kept
        except KeyringError as e:
            self.problem = str(e)
