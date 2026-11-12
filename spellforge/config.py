"""Global configuration and shared constants for SpellForge."""

from __future__ import annotations

import pygame

# ---------------------------------------------------------------------------
# Window / layout
# ---------------------------------------------------------------------------
TITLE = "SpellForge - Arcane Sandbox"
WINDOW_W, WINDOW_H = 1440, 720
FPS = 60
SIM_HZ = 60
DT = 1.0 / SIM_HZ

TILE = 6
GRID_W, GRID_H = 180, 100
WORLD_W, WORLD_H = GRID_W * TILE, GRID_H * TILE  # 1080 x 600
WORLD_X, WORLD_Y = 12, 72

PANEL_X = WORLD_X + WORLD_W + 12
PANEL_W = WINDOW_W - PANEL_X - 12
PANEL_Y = WORLD_Y
PANEL_H = WORLD_H

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG = (10, 11, 18)
BG_PANEL = (20, 22, 34)
BG_PANEL_LIGHT = (29, 32, 48)
BORDER = (52, 56, 82)
TEXT = (218, 222, 240)
TEXT_DIM = (132, 139, 166)
TEXT_FAINT = (88, 94, 118)
ACCENT = (168, 120, 255)
ACCENT_DIM = (94, 68, 150)
GOLD = (240, 196, 96)
RED = (232, 92, 92)
GREEN = (108, 220, 140)
CYAN = (112, 220, 240)
ORANGE = (255, 148, 72)

# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------
ELEMENTS = {
    "fire": {
        "color": (255, 128, 48),
        "glow": (255, 96, 32),
        "material": "fire",
        "damage": 1.00,
        "desc": "Burns. Ignites wood, oil and plants. Melts ice, boils water.",
    },
    "water": {
        "color": (64, 148, 255),
        "glow": (40, 110, 230),
        "material": "water",
        "damage": 0.55,
        "desc": "Douses fire, cools lava, wets targets. Conducts lightning.",
    },
    "ice": {
        "color": (150, 232, 255),
        "glow": (110, 200, 240),
        "material": "ice",
        "damage": 0.75,
        "desc": "Freezes water into ice and chills enemies, slowing them.",
    },
    "earth": {
        "color": (176, 132, 78),
        "glow": (140, 100, 50),
        "material": "stone",
        "damage": 1.15,
        "desc": "Conjures solid stone. Heavy, blunt damage.",
    },
    "air": {
        "color": (214, 232, 244),
        "glow": (180, 210, 230),
        "material": None,
        "damage": 0.35,
        "desc": "A violent gust. Pushes enemies. No material.",
    },
    "lightning": {
        "color": (255, 244, 140),
        "glow": (255, 226, 80),
        "material": None,
        "damage": 1.35,
        "desc": "Chains through water and wet targets. Very high damage.",
    },
    "poison": {
        "color": (138, 224, 96),
        "glow": (100, 190, 60),
        "material": "acid",
        "damage": 0.45,
        "desc": "Spills acid that dissolves solids. Poisons living targets.",
    },
    "arcane": {
        "color": (190, 132, 255),
        "glow": (150, 90, 230),
        "material": None,
        "damage": 1.10,
        "desc": "Raw mana. Reliable damage with no material side effects.",
    },
    "light": {
        "color": (255, 248, 210),
        "glow": (255, 236, 160),
        "material": None,
        "damage": 0.85,
        "desc": "Purifying radiance. Burns the undead and reveals the dark.",
    },
    "dark": {
        "color": (128, 92, 196),
        "glow": (90, 50, 150),
        "material": None,
        "damage": 0.95,
        "desc": "Drains life from targets, healing the caster for a share.",
    },
}

ELEMENT_NAMES = tuple(ELEMENTS)
