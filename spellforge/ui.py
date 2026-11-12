"""HUD, overlays and menus."""

from __future__ import annotations

import math

import pygame

from .challenges import CHALLENGES
from .config import (ACCENT, ACCENT_DIM, BG, BG_PANEL, BG_PANEL_LIGHT, BORDER, CYAN,
                     ELEMENTS, GOLD, GREEN, ORANGE, PANEL_H, PANEL_W, PANEL_X, PANEL_Y,
                     RED, TEXT, TEXT_DIM, TEXT_FAINT, WINDOW_H, WINDOW_W, WORLD_H,
                     WORLD_X, WORLD_Y)
from .gfx import bar, draw_text, font, panel, text_width, wrap
from .spell_lang import INSTRUCTIONS, INSTRUCTION_NAMES

# Sidebar layout (shared with game.py hit testing)
VITALS_H = 92
SLOTS_Y = PANEL_Y + 100
SLOT_ROW_H = 27
SLOTS_H = 24 + 9 * SLOT_ROW_H + 8
CH_Y = SLOTS_Y + SLOTS_H + 8
CH_H = 68
CTL_Y = CH_Y + CH_H + 8


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _diamond(surf, center, color, size=5):
    x, y = center
    pygame.draw.polygon(surf, color, [(x, y - size), (x + size, y), (x, y + size), (x - size, y)])
    pygame.draw.polygon(surf, (255, 255, 255), [(x, y - size), (x + size, y), (x, y + size), (x - size, y)], 1)


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def draw_focus_hint(surf) -> None:
    w = 430
    rect = pygame.Rect((WINDOW_W - w) // 2, WORLD_Y + WORLD_H - 56, w, 36)
    panel(surf, rect, (16, 17, 28), GOLD, radius=10, alpha=232)
    draw_text(surf, "Click the game window to focus the keyboard",
              (rect.centerx, rect.y + 10), 12, GOLD, bold=True, align="center")


def draw_toasts(surf, game) -> None:
    y = WORLD_Y + 12
    for text, color, timer, total in game.toasts:
        alpha = int(255 * min(1.0, timer / 0.5, (total - timer) / 0.25 + 0.2))
        w = text_width(text, 13, bold=True) + 28
        rect = pygame.Rect(WORLD_X + (game.world_rect.w - w) // 2, y, w, 28)
        panel(surf, rect, (16, 17, 26), color, radius=14, alpha=235)
        draw_text(surf, text, (rect.centerx, rect.y + 6), 13, color, bold=True,
                  align="center", alpha=alpha)
        y += 34


def draw_world_frame(surf, game) -> None:
    rect = game.world_rect
    pygame.draw.rect(surf, BORDER, rect.inflate(2, 2), 1, border_radius=3)
    pygame.draw.rect(surf, (2, 3, 6), rect.inflate(8, 8), 2, border_radius=5)


# ---------------------------------------------------------------------------
# Main HUD
# ---------------------------------------------------------------------------
def draw_hud(surf, game) -> None:
    rect = game.world_rect
    draw_world_frame(surf, game)
    selected = game.selected_spell
    elem = game.selected_element

    # Top bar ---------------------------------------------------------
    draw_text(surf, "SPELLFORGE", (WORLD_X, 16), 24, TEXT, bold=True)
    draw_text(surf, "arcana sandbox", (WORLD_X + 172, 24), 11, TEXT_FAINT)
    draw_text(surf, f"{game.clock.get_fps():.0f} fps", (WORLD_X + 330, 24), 11, TEXT_FAINT)
    hint = "E code   G weave   TAB book   H help   C quests   ESC pause"
    draw_text(surf, hint, (WINDOW_W - 16, 24), 11, TEXT_DIM, align="right")
    if game.spellbook.errors:
        draw_text(surf, f"{len(game.spellbook.errors)} SPELL ERROR(S)", (WINDOW_W - 16, 40), 10,
                  RED, bold=True, align="right")

    # Vitals ----------------------------------------------------------
    x = PANEL_X
    y = PANEL_Y
    vit = pygame.Rect(x, y, PANEL_W, VITALS_H)
    panel(surf, vit, BG_PANEL, BORDER)
    draw_text(surf, "THE WIZARD", (x + 12, y + 8), 11, TEXT_DIM, bold=True)
    draw_text(surf, f"LVL {game.level}", (x + PANEL_W - 12, y + 8), 10, GOLD,
              bold=True, align="right")
    p = game.player
    draw_text(surf, f"HP {int(p.hp)}/{int(p.max_hp)}", (x + 12, y + 26), 10, TEXT)
    bar(surf, pygame.Rect(x + 12, y + 41, PANEL_W - 24, 8), p.hp, p.max_hp, (214, 78, 88))
    draw_text(surf, f"MANA {int(p.mana)}/{int(p.max_mana)}", (x + 12, y + 51), 10, TEXT)
    bar(surf, pygame.Rect(x + 12, y + 66, PANEL_W - 24, 8), p.mana, p.max_mana, (82, 128, 232))
    draw_text(surf, f"XP {game.xp}/{game.xp_to_next}", (x + 12, y + 77), 9, TEXT_FAINT)
    draw_text(surf, f"{int(game.stats.get('kills', 0))} kills",
              (x + PANEL_W - 12, y + 77), 9, TEXT_FAINT, align="right")

    # Spell slots -----------------------------------------------------
    y = SLOTS_Y
    spells = game.spells[:9]
    h = 24 + len(spells) * SLOT_ROW_H + 8
    slots = pygame.Rect(x, y, PANEL_W, h)
    panel(surf, slots, BG_PANEL, BORDER)
    draw_text(surf, "SPELL SLOTS", (x + 12, y + 7), 10, TEXT_DIM, bold=True)
    draw_text(surf, "wheel cycles", (x + PANEL_W - 12, y + 8), 9, TEXT_FAINT, align="right")
    sy = y + 24
    for i, spell in enumerate(spells):
        row = pygame.Rect(x + 6, sy, PANEL_W - 12, 25)
        is_sel = i == game.selected_index
        hover = row.collidepoint(game.mouse_pos)
        if is_sel:
            pygame.draw.rect(surf, (44, 38, 66), row, border_radius=5)
            pygame.draw.rect(surf, ACCENT, row, 1, border_radius=5)
        elif hover:
            pygame.draw.rect(surf, BG_PANEL_LIGHT, row, border_radius=5)
        draw_text(surf, str(i + 1), (row.x + 8, row.y + 5), 11, GOLD if is_sel else TEXT_DIM,
                  bold=True, mono=True)
        _diamond(surf, (row.x + 26, row.y + 12), ELEMENTS[spell.element]["color"], 4)
        draw_text(surf, spell.name, (row.x + 37, row.y + 4), 11,
                  TEXT if is_sel else (196, 200, 218))
        draw_text(surf, str(spell.mana), (row.right - 8, row.y + 5), 10,
                  (110, 150, 230) if p.mana >= spell.mana else (150, 90, 100), align="right")
        cd = p.cooldowns.get(spell.name, 0.0)
        if cd > 0:
            ratio = cd / max(0.001, spell.cooldown)
            pygame.draw.rect(surf, (70, 60, 90),
                             (row.x + 2, row.bottom - 3, int((row.w - 4) * (1 - ratio)), 2),
                             border_radius=1)
        sy += SLOT_ROW_H
    if not spells:
        draw_text(surf, "No spells compiled. Press E.", (x + 12, y + 34), 11, RED)

    # Quest ------------------------------------------------------------
    y = CH_Y
    ch = pygame.Rect(x, y, PANEL_W, CH_H)
    panel(surf, ch, BG_PANEL, BORDER)
    quest = game.current_quest
    draw_text(surf, "QUEST", (x + 12, y + 6), 10, TEXT_DIM, bold=True)
    draw_text(surf, f"{min(game.quest_index + 1, game.quest_total)}/{game.quest_total}",
              (x + PANEL_W - 12, y + 6), 10, GOLD, bold=True, align="right")
    if quest is not None:
        value = game.quest_progress
        draw_text(surf, quest.title, (x + 12, y + 21), 11, TEXT, bold=True)
        draw_text(surf, f"{_fmt_num(value)}/{_fmt_num(quest.goal)} {quest.unit}",
                  (x + PANEL_W - 12, y + 22), 9, TEXT_DIM, align="right")
        bar(surf, pygame.Rect(x + 12, y + 39, PANEL_W - 24, 6), value, quest.goal, ACCENT)
        desc = wrap(quest.desc, PANEL_W - 24, 9)
        draw_text(surf, desc[0] if desc else "", (x + 12, y + 50), 9, TEXT_FAINT)
    else:
        draw_text(surf, "All quests complete.", (x + 12, y + 22), 11, GREEN)
        draw_text(surf, "The sandbox is yours.", (x + 12, y + 40), 9, TEXT_FAINT)

    # Controls --------------------------------------------------------
    y = CTL_Y
    ctl = pygame.Rect(x, y, PANEL_W, WORLD_Y + PANEL_H - y)
    panel(surf, ctl, BG_PANEL, BORDER)
    draw_text(surf, "CONTROLS", (x + 12, y + 6), 10, TEXT_DIM, bold=True)
    lines = [
        ("WASD", "move"), ("LMB", "cast spell"), ("1-9", "select spell"),
        ("E", "spell code"), ("G", "weave canvas"), ("TAB", "all spells"),
        ("H", "language help"), ("C", "quests"), ("F2", "reset arena"),
        ("F3", "debug info"), ("M", "mute sound"),
    ]
    ly = y + 18
    for key, desc in lines:
        draw_text(surf, key, (x + 12, ly), 9, GOLD, mono=True)
        draw_text(surf, desc, (x + 56, ly), 9, TEXT_FAINT)
        ly += 11

    draw_toasts(surf, game)

    # Bottom bar ------------------------------------------------------
    by = WORLD_Y + PANEL_H + 8
    barrect = pygame.Rect(WORLD_X, by, WINDOW_W - 24, 34)
    panel(surf, barrect, BG_PANEL, BORDER)
    if game.spellbook.errors:
        err = game.spellbook.errors[0]
        draw_text(surf, f"Compile error in {err.filename or 'spell'} line {err.line}: {err.message}",
                  (WORLD_X + 12, by + 9), 11, RED)
        draw_text(surf, "press E to open the editor", (WINDOW_W - 20, by + 10), 10,
                  TEXT_FAINT, align="right")
    elif selected:
        draw_text(surf, selected.name, (WORLD_X + 12, by + 7), 13,
                  ELEMENTS[elem]["color"], bold=True)
        draw_text(surf, selected.desc or "No description.",
                  (WORLD_X + 12 + text_width(selected.name, 13, True) + 14, by + 10), 11, TEXT_DIM)
        draw_text(surf, f"{selected.mana} mana   cost {selected.cost}   "
                        f"{'READY' if p.cooldowns.get(selected.name, 0) <= 0 else 'COOLDOWN'}",
                  (WINDOW_W - 20, by + 10), 10,
                  GREEN if p.cooldowns.get(selected.name, 0) <= 0 else ORANGE, align="right")
    else:
        draw_text(surf, "No spell selected.", (WORLD_X + 12, by + 10), 11, TEXT_FAINT)

    if game.debug:
        draw_debug(surf, game)


def draw_debug(surf, game) -> None:
    lines = [
        f"fps {game.clock.get_fps():.0f}",
        f"active tiles {len(game.world.active)}",
        f"enemies {sum(1 for e in game.enemies if e.alive)}/{len(game.enemies)}",
        f"projectiles {len(game.projectiles)}  particles {len(game.particles.items)}",
        f"fields {len(game.fields)}  shields {len(game.shields)}  timers {len(game.timed_tiles)}",
        f"mouse {int(game.mouse_world[0])},{int(game.mouse_world[1])}",
        f"state {game.state}",
    ]
    w = 240
    rect = pygame.Rect(WINDOW_W - w - 16, WINDOW_H - 24 - len(lines) * 15 - 12, w,
                       len(lines) * 15 + 12)
    panel(surf, rect, (8, 9, 14), BORDER, alpha=230)
    for i, line in enumerate(lines):
        draw_text(surf, line, (rect.x + 8, rect.y + 6 + i * 15), 10, CYAN, mono=True)


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------
def _dim(surf, alpha=200):
    layer = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
    layer.fill((3, 4, 9, alpha))
    surf.blit(layer, (0, 0))


def draw_help(surf, game) -> None:
    _dim(surf, 215)
    outer = pygame.Rect(48, 28, WINDOW_W - 96, WINDOW_H - 56)
    panel(surf, outer, (13, 15, 24), BORDER, radius=12)
    draw_text(surf, "SPELL LANGUAGE REFERENCE", (outer.x + 22, outer.y + 14), 20, TEXT, bold=True)
    draw_text(surf, "H / ESC to close", (outer.right - 22, outer.y + 22), 11, TEXT_FAINT,
              align="right")

    col_w = (outer.w - 60) // 3
    c1 = outer.x + 22
    c2 = c1 + col_w + 12
    c3 = c2 + col_w + 12
    top = outer.y + 52

    def heading(x, y, text):
        draw_text(surf, text, (x, y), 12, ACCENT, bold=True)
        pygame.draw.line(surf, BORDER, (x, y + 18), (x + col_w - 8, y + 18), 1)
        return y + 28

    # Column 1: grammar -----------------------------------------------
    y = heading(c1, top, "ANATOMY")
    sample = [
        "spell Fireball {",
        "  mana 22",
        "  cooldown 0.9",
        '  desc "Explosive ember."',
        "",
        "  cast {",
        "    bolt fire speed=36 size=5 power=1.1 {",
        "      on hit {",
        "        burst fire radius=1.9 power=1.2",
        "      }",
        "    }",
        "  }",
        "}",
    ]
    for line in sample:
        draw_text(surf, line, (c1, y), 10, (170, 200, 210), mono=True)
        y += 13
    y += 10
    rules = [
        "One spell per .spell file in /spells.",
        "Headers: mana, cooldown, desc. Exactly one cast block.",
        "mana must be >= the compiled cost. The editor",
        "shows the cost live; the compiler rejects cheap spells.",
        "Every instruction is checked: unknown names, unknown",
        "parameters, wrong types and out of range values fail",
        "with a line:column and a suggestion.",
        "Events: 'on hit' (bolt, beam), 'on expire' (bolt).",
        "Event blocks cannot nest. Max 60 instructions.",
        "Cooldown 0.05..20s. Mana 1..300.",
        "Coordinates: offset in tiles. speed is tiles/second.",
        "radius/length/height/size in tiles.",
    ]
    for line in rules:
        for part in wrap(line, col_w - 10, 10):
            draw_text(surf, part, (c1, y), 10, TEXT_DIM)
            y += 13
        y += 2
    y += 6
    y = heading(c1, y, "ELEMENTS")
    for name, data in ELEMENTS.items():
        draw_text(surf, name, (c1, y), 10, data["color"], mono=True)
        for j, line in enumerate(wrap(data["desc"], col_w - 90, 9)[:2]):
            draw_text(surf, line, (c1 + 78, y + j * 11), 9, TEXT_FAINT)
        y += 24 if len(wrap(data["desc"], col_w - 90, 9)) > 1 else 14

    # Column 2: instructions ------------------------------------------
    y = heading(c2, top, "INSTRUCTIONS")
    for name in INSTRUCTION_NAMES:
        spec = INSTRUCTIONS[name]
        draw_text(surf, name + (" <element>" if spec.takes_element else ""),
                  (c2, y), 11, (198, 152, 255), mono=True)
        y += 14
        for line in wrap(spec.summary, col_w - 14, 9)[:2]:
            draw_text(surf, line, (c2 + 8, y), 9, TEXT_FAINT)
            y += 11
        params = ", ".join(
            f"{p.name}={_fmt_num(p.default)}" for p in spec.params
        )
        for line in wrap(params or "no parameters", col_w - 14, 9):
            draw_text(surf, line, (c2 + 8, y), 9, (110, 140, 160), mono=True)
            y += 11
        y += 7

    # Column 3: reactions + controls ----------------------------------
    y = heading(c3, top, "MATERIAL REACTIONS")
    reactions = [
        "fire + wood/plant/oil  ->  ignition",
        "fire + water  ->  steam, fire is put out",
        "fire + ice  ->  melt into water",
        "lava + water  ->  stone + steam",
        "acid + stone/wood/ice  ->  dissolved",
        "ice spell + water  ->  frozen solid",
        "lightning + water or wet target  ->  1.5x damage",
        "water on fire  ->  douses, wets targets",
        "burning/poisoned/chilled entities take damage",
        "over time and can die from it",
    ]
    for line in reactions:
        for part in wrap(line, col_w - 8, 10):
            draw_text(surf, part, (c3, y), 10, TEXT_DIM)
            y += 13
    y += 10
    y = heading(c3, y, "CONTROLS")
    controls = [
        ("WASD", "walk"), ("Mouse", "aim"), ("LMB", "cast / hold"),
        ("1-9 / wheel", "select spell"), ("E", "spell code"),
        ("G", "weave canvas"), ("TAB", "spellbook"), ("C", "quests"),
        ("F2", "reset arena"), ("F3", "debug"), ("M", "mute audio"),
        ("ESC", "pause"),
    ]
    for key, desc in controls:
        draw_text(surf, key, (c3, y), 10, GOLD, mono=True)
        draw_text(surf, desc, (c3 + 110, y), 10, TEXT_DIM)
        y += 15
    y += 8
    y = heading(c3, y, "TIPS")
    tips = [
        "Set oil alight, then hit it with lightning.",
        "A Ward blocks Watcher bolts while you cast.",
        "Stonefist can wall off a corridor.",
        "Frostwall buys time; it melts near fire.",
        "Write a spell with E, or weave one on the canvas with G.",
    ]
    for line in tips:
        for part in wrap("- " + line, col_w - 8, 10):
            draw_text(surf, part, (c3, y), 10, TEXT_FAINT)
            y += 13


def draw_tutorial(surf, game) -> None:
    _dim(surf, 195)
    outer = pygame.Rect(230, 90, WINDOW_W - 460, 500)
    panel(surf, outer, (13, 15, 24), ACCENT_DIM, radius=12)
    draw_text(surf, "WELCOME, WIZARD", (outer.x + 28, outer.y + 18), 24, TEXT, bold=True)
    draw_text(surf, "SpellForge is a sandbox where you build spells instead of unlocking them.",
              (outer.x + 28, outer.y + 52), 11, TEXT_DIM)
    draw_text(surf, f"Level {game.level}   ·   {int(game.player.max_mana)} max mana",
              (outer.right - 28, outer.y + 22), 11, GOLD, align="right")

    left = outer.x + 28
    right = outer.x + 482
    col_w = 430
    y = outer.y + 92
    draw_text(surf, "MOVE AND CAST", (left, y), 11, ACCENT, bold=True)
    y += 20
    for line in ("WASD or arrow keys to move.",
                 "The mouse aims. The left button casts.",
                 "1-9 or the mouse wheel selects a spell.",
                 "Hold the left button to keep casting."):
        draw_text(surf, "- " + line, (left, y), 10, TEXT_DIM)
        y += 17

    y += 18
    draw_text(surf, "QUESTS ARE SEQUENTIAL", (left, y), 11, ACCENT, bold=True)
    y += 20
    for line in ("Press C to open the quest log.",
                 "Only the current quest can be completed.",
                 "Each quest pays XP and some unlock canvas sizes.",
                 "The current objective is always shown in the sidebar."):
        for part in wrap("- " + line, col_w, 10):
            draw_text(surf, part, (left, y), 10, TEXT_DIM)
            y += 16
        y += 1

    y += 18
    draw_text(surf, "CANVAS SIZES", (left, y), 11, ACCENT, bold=True)
    y += 20
    for line in ("SMALL — 100 mana, available now.",
                 "MEDIUM — 500 mana, unlocked by quest 3.",
                 "HIGH — 1000 mana, unlocked by quest 10."):
        draw_text(surf, "- " + line, (left, y), 10, TEXT_DIM)
        y += 17

    y = outer.y + 92
    draw_text(surf, "WEAVE CANVAS  (G)", (right, y), 11, ACCENT, bold=True)
    y += 20
    for line in ("Build spells from elemental runes and arrows.",
                 "Only SMALL (100 mana) is unlocked at first.",
                 "Place runes, then right-drag to weave a relation.",
                 "Curve the drag to bend the arrow.",
                 "Wheel over a rune (or [ ]) to resize it; bigger runes cost more.",
                 "Longer or more curved arrows cost more mana.",
                 "A ring of Air runes becomes a Tornado.",
                 "At level 3, woven spells become reusable nodes."):
        for part in wrap("- " + line, col_w, 10):
            draw_text(surf, part, (right, y), 10, TEXT_DIM)
            y += 16
        y += 1

    y += 18
    draw_text(surf, "LEVELS AND MANA", (right, y), 11, ACCENT, bold=True)
    y += 20
    for line in ("Kills and completed quests grant XP.",
                 "Level 1 starts with 1000 maximum mana.",
                 "Each level adds 10% to the previous maximum.",
                 "Level-ups refill your mana completely.",
                 "Woven spells cast at 80% of their raw mana."):
        draw_text(surf, "- " + line, (right, y), 10, TEXT_DIM)
        y += 17

    quest = game.current_quest
    if quest is not None:
        draw_text(surf, "FIRST OBJECTIVE", (outer.x + 28, outer.bottom - 70), 9, GOLD,
                  bold=True)
        draw_text(surf, f"{quest.title}  ·  {quest.desc}",
                  (outer.x + 28, outer.bottom - 55), 11, TEXT)
    draw_text(surf, "Click or press any key to begin.",
              (outer.centerx, outer.bottom - 30), 12, ACCENT, bold=True, align="center")


def draw_challenges(surf, game) -> None:
    _dim(surf, 205)
    outer = pygame.Rect(190, 36, WINDOW_W - 380, WINDOW_H - 72)
    panel(surf, outer, (13, 15, 24), BORDER, radius=12)
    draw_text(surf, "QUESTS", (outer.x + 22, outer.y + 14), 22, TEXT, bold=True)
    draw_text(surf, f"COMPLETED {len(game.quest_completed)} / {game.quest_total}",
              (outer.x + 150, outer.y + 22), 10, TEXT_FAINT)
    draw_text(surf, "C / ESC to close", (outer.right - 22, outer.y + 22), 11, TEXT_FAINT,
              align="right")

    quest = game.current_quest
    card = pygame.Rect(outer.x + 18, outer.y + 56, outer.w - 36, 132)
    pygame.draw.rect(surf, (32, 28, 50), card, border_radius=9)
    pygame.draw.rect(surf, ACCENT, card, 1, border_radius=9)
    draw_text(surf, "CURRENT QUEST", (card.x + 16, card.y + 8), 9, ACCENT, bold=True)
    if quest is not None:
        draw_text(surf, quest.title, (card.x + 16, card.y + 24), 17, TEXT, bold=True)
        value = game.quest_progress
        draw_text(surf, f"{_fmt_num(value)} / {_fmt_num(quest.goal)} {quest.unit}",
                  (card.right - 16, card.y + 28), 10, TEXT_DIM, align="right")
        bar(surf, pygame.Rect(card.x + 16, card.y + 48, card.w - 32, 6), value, quest.goal,
            ACCENT)
        draw_text(surf, quest.desc, (card.x + 16, card.y + 62), 10, TEXT_DIM)
        y = card.y + 82
        for part in wrap(quest.hint, card.w - 32, 9)[:2]:
            draw_text(surf, part, (card.x + 16, y), 9, TEXT_FAINT)
            y += 12
        reward = f"+{quest.reward_xp} XP"
        if quest.unlock:
            label = {"medium": "MEDIUM", "large": "HIGH"}.get(
                quest.unlock, quest.unlock.upper())
            reward += f"   ·   unlocks {label} canvas"
        draw_text(surf, reward, (card.right - 16, card.bottom - 20), 9, GOLD, align="right")
    else:
        draw_text(surf, "All quests complete.", (card.x + 16, card.y + 28), 17, GREEN,
                  bold=True)
        draw_text(surf, "The arena is yours. Build, burn, freeze and dissolve as you like.",
                  (card.x + 16, card.y + 58), 10, TEXT_DIM)

    y = card.bottom + 14
    for i, ch in enumerate(CHALLENGES):
        done = ch.id in game.quest_completed
        current = i == game.quest_index
        row = pygame.Rect(outer.x + 18, y, outer.w - 36, 27)
        if done:
            pygame.draw.rect(surf, (25, 38, 30), row, border_radius=6)
            pygame.draw.rect(surf, (56, 100, 66), row, 1, border_radius=6)
        elif current:
            pygame.draw.rect(surf, (38, 33, 58), row, border_radius=6)
            pygame.draw.rect(surf, ACCENT, row, 1, border_radius=6)
        else:
            pygame.draw.rect(surf, BG_PANEL, row, border_radius=6)
        if done:
            pygame.draw.lines(surf, GREEN, False,
                              [(row.x + 16, row.y + 14), (row.x + 20, row.y + 18),
                               (row.x + 27, row.y + 8)], 2)
        elif current:
            _diamond(surf, (row.x + 21, row.centery), ACCENT, 5)
        else:
            pygame.draw.rect(surf, TEXT_FAINT, (row.x + 18, row.y + 12, 6, 5), 1)
            pygame.draw.circle(surf, TEXT_FAINT, (row.x + 21, row.y + 11), 3, 1)
        draw_text(surf, ch.title, (row.x + 38, row.y + 7), 11,
                  GREEN if done else TEXT if current else TEXT_FAINT,
                  bold=current)
        tag = "DONE" if done else "CURRENT" if current else "LOCKED"
        draw_text(surf, tag, (row.right - 16, row.y + 8), 9,
                  GREEN if done else ACCENT if current else TEXT_FAINT,
                  bold=current, align="right")
        y += 30

    footer = "Quests are sequential: finish the current one to advance."
    draw_text(surf, footer, (outer.x + 22, outer.bottom - 24), 10, TEXT_FAINT)
    labels = []
    for key, label in (("small", "SMALL 100"), ("medium", "MEDIUM 500"),
                       ("large", "HIGH 1000")):
        labels.append(label if key in game.unlocked_canvases else f"LOCKED {label}")
    draw_text(surf, "CANVAS:  " + "   ·   ".join(labels),
              (outer.right - 22, outer.bottom - 24), 10, TEXT_DIM, align="right")


def draw_spellbook(surf, game) -> None:
    _dim(surf, 205)
    outer = pygame.Rect(70, 48, WINDOW_W - 140, WINDOW_H - 96)
    panel(surf, outer, (13, 15, 24), BORDER, radius=12)
    draw_text(surf, "SPELLBOOK", (outer.x + 22, outer.y + 14), 20, TEXT, bold=True)
    draw_text(surf, "TAB / ESC to close   click a spell to select",
              (outer.right - 22, outer.y + 22), 11, TEXT_FAINT, align="right")

    spells = game.spells
    cols = 3
    card_w = (outer.w - 56) // cols
    card_h = 84
    x0 = outer.x + 20
    y0 = outer.y + 54
    for i, spell in enumerate(spells):
        col = i % cols
        row = i // cols
        rect = pygame.Rect(x0 + col * (card_w + 8), y0 + row * (card_h + 8), card_w, card_h)
        if rect.bottom > outer.bottom - 20:
            break
        sel = i == game.selected_index
        pygame.draw.rect(surf, (34, 30, 52) if sel else BG_PANEL, rect, border_radius=8)
        pygame.draw.rect(surf, ACCENT if sel else BORDER, rect, 1, border_radius=8)
        key = str(i + 1) if i < 9 else "-"
        draw_text(surf, key, (rect.x + 10, rect.y + 8), 11, GOLD, bold=True, mono=True)
        _diamond(surf, (rect.x + 30, rect.y + 16), ELEMENTS[spell.element]["color"], 4)
        draw_text(surf, spell.name, (rect.x + 42, rect.y + 6), 14, TEXT, bold=True)
        draw_text(surf, f"{spell.mana} mana / cost {spell.cost}", (rect.right - 10, rect.y + 8),
                  9, TEXT_DIM, align="right")
        desc = spell.desc or "No description."
        for j, line in enumerate(wrap(desc, card_w - 20, 10)[:2]):
            draw_text(surf, line, (rect.x + 10, rect.y + 28 + j * 12), 10, TEXT_DIM)
        tag = "   WEAVE" if spell.path.lower().endswith(".weave") else ""
        draw_text(surf, f"{spell.element}  ·  {spell.cooldown:g}s{tag}", (rect.x + 10, rect.y + 58),
                  10, ELEMENTS[spell.element]["color"])
    if not spells:
        draw_text(surf, "No spells found in /spells. Press E to write one.",
                  (outer.centerx, outer.centery), 14, RED, align="center")


def draw_pause(surf, game) -> None:
    _dim(surf, 215)
    outer = pygame.Rect(WINDOW_W // 2 - 230, WINDOW_H // 2 - 150, 460, 300)
    panel(surf, outer, (13, 15, 24), BORDER, radius=12)
    draw_text(surf, "PAUSED", (outer.centerx, outer.y + 30), 28, TEXT, bold=True, align="center")
    draw_text(surf, "The sandbox waits.", (outer.centerx, outer.y + 70), 12, TEXT_DIM,
              align="center")
    buttons = [("RESUME", "resume"), ("RESET ARENA", "reset"), ("QUIT", "quit")]
    game.pause_buttons = {}
    y = outer.y + 108
    for label, key in buttons:
        rect = pygame.Rect(outer.centerx - 140, y, 280, 40)
        hover = rect.collidepoint(game.mouse_pos)
        pygame.draw.rect(surf, (44, 38, 66) if hover else BG_PANEL_LIGHT, rect, border_radius=7)
        pygame.draw.rect(surf, ACCENT if hover else BORDER, rect, 1, border_radius=7)
        draw_text(surf, label, (rect.centerx, rect.y + 11), 13, TEXT, bold=True, align="center")
        game.pause_buttons[key] = rect
        y += 52
    draw_text(surf, "ESC resumes", (outer.centerx, outer.bottom - 24), 10, TEXT_FAINT,
              align="center")
