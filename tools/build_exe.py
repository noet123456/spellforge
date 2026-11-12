"""Build a standalone Windows build of SpellForge.

    python tools/build_exe.py

Outputs ``dist/SpellForge.exe`` (single file, no console window).  The bundled
``spells/`` folder is copied next to the exe on first launch, so players can
still edit spells and save weaves.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
ICON = os.path.join(BUILD, "icon.ico")


def make_icon() -> str:
    """Render the game rune to a 256x256 PNG and wrap it in an .ico container."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.makedirs(BUILD, exist_ok=True)

    import math

    import pygame

    pygame.init()
    surf = pygame.Surface((256, 256), pygame.SRCALPHA)
    surf.fill((14, 12, 24))
    pygame.draw.circle(surf, (34, 27, 58), (128, 128), 124)
    pygame.draw.circle(surf, (150, 120, 235), (128, 128), 124, 5)
    for i in range(6):
        ang = math.tau * i / 6 - math.pi / 2
        x = 128 + math.cos(ang) * 72
        y = 128 + math.sin(ang) * 72
        pygame.draw.circle(surf, (240, 220, 255), (int(x), int(y)), 13)
        pygame.draw.circle(surf, (120, 90, 210), (int(x), int(y)), 13, 2)
    pygame.draw.circle(surf, (255, 248, 220), (128, 128), 15)

    png_path = os.path.join(BUILD, "icon.png")
    pygame.image.save(surf, png_path)
    pygame.quit()

    with open(png_path, "rb") as fh:
        png = fh.read()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    with open(ICON, "wb") as fh:
        fh.write(header + entry + png)
    return ICON


def build() -> int:
    icon = make_icon()
    for stale in (os.path.join(ROOT, "SpellForge.spec"),):
        if os.path.exists(stale):
            os.remove(stale)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "SpellForge",
        "--icon", icon,
        "--add-data", f"spells{os.pathsep}spells",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc_data",
        "--exclude-module", "test",
        os.path.join(ROOT, "run.py"),
    ]
    print(" ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        return rc

    for name in ("README.md", "requirements.txt"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DIST, name))
    print(f"\nBuilt {os.path.join(DIST, 'SpellForge.exe')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
