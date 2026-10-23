"""Dossier errors with stable codes for CLI and model recovery."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DossierError(Exception):
    code: str
    message: str
    hint: str = ""

    def __str__(self) -> str:
        return f"{self.code}: {self.message}" + (f"\n  {self.hint}" if self.hint else "")


class DossierCorrupt(DossierError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__("E_DOSSIER_CORRUPT", message, hint)


class SchemaTooNew(DossierError):
    def __init__(self, found: int, supported: int):
        super().__init__(
            "E_DOSSIER_TOO_NEW",
            f"dossier schema {found} is newer than this reader ({supported})",
            "Update anki-gen or open the dossier read-only; do not rewrite it.")


class DossierLocked(DossierError):
    def __init__(self, path: str):
        super().__init__("E_DOSSIER_LOCKED",
                         f"another anki-gen process holds the dossier lock: {path}",
                         "Wait for it to finish, or remove a stale lock after "
                         "checking no anki-gen process is running.")


class ArchiveError(DossierError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__("E_ARCHIVE", message, hint)
