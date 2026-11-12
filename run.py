"""SpellForge - a sandbox of programmable magic.

Run from source:   python run.py
Run the packaged build:  SpellForge.exe
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spellforge.game import Game


def _base_dir() -> str:
    """Folder the game treats as its home: next to the exe, or the repo root."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _bundle_dir() -> str:
    """Read-only folder holding data bundled by PyInstaller."""
    return getattr(sys, "_MEIPASS", _base_dir())


def _writable(root: str) -> bool:
    probe = os.path.join(root, ".spellforge_write_test")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _home_dir() -> str:
    """Prefer a portable install; fall back to %APPDATA% when read-only."""
    base = _base_dir()
    if _writable(base):
        return base
    fallback = os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "SpellForge")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _ensure_spells(home: str) -> str:
    """Ship the bundled spells next to the game so players can edit them."""
    spells_dir = os.path.join(home, "spells")
    bundled = os.path.join(_bundle_dir(), "spells")
    if not os.path.isdir(spells_dir) or not os.listdir(spells_dir):
        if os.path.isdir(bundled) and os.path.abspath(bundled) != os.path.abspath(spells_dir):
            shutil.copytree(bundled, spells_dir, dirs_exist_ok=True)
    os.makedirs(spells_dir, exist_ok=True)
    return spells_dir


def _report_failure(home: str) -> None:
    """No console in the packaged build: keep a log and show a message box."""
    import traceback

    log_path = os.path.join(home, "spellforge_error.log")
    text = traceback.format_exc()
    try:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        log_path = "<could not write log>"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "SpellForge crashed.\n\n"
            f"{text.strip().splitlines()[-1]}\n\nFull log: {log_path}",
            "SpellForge", 0x10,
        )
    except Exception:
        pass


def main() -> None:
    home = _home_dir()
    try:
        spells_dir = _ensure_spells(home)
        game = Game(spells_dir)
        game.run()
    except Exception:
        _report_failure(home)
        raise


if __name__ == "__main__":
    main()
