"""Main game loop, state machine and world orchestration."""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time

import pygame
from pygame import Vector2

from .audio import Audio
from .challenges import CHALLENGES
from .config import (ACCENT, BG, DT, ELEMENTS, FPS, GRID_H, GRID_W, PANEL_H, PANEL_W,
                     PANEL_X, PANEL_Y, RED, TILE, TITLE, WINDOW_H, WINDOW_W, WORLD_H,
                     WORLD_W, WORLD_X, WORLD_Y)
from .editor import Editor
from .effects import FloatingText, ParticleSystem, Projectile, Ring
from .entities import Dummy, Player, make_eye, make_stalker, move_circle
from .render import WorldRenderer
from .runtime import SpellRuntime
from .spell_lang import Spellbook, SpellError, load_spellbook
from .weave import load_weave
from .ui import (SLOT_ROW_H, SLOTS_Y, draw_challenges, draw_focus_hint, draw_help,
                 draw_hud, draw_pause, draw_spellbook, draw_tutorial)
from .weave_ui import WeaveEditor
from .world import EMPTY, FIRE, STEAM, WATER, World


def _make_icon() -> pygame.Surface:
    icon = pygame.Surface((32, 32), pygame.SRCALPHA)
    pygame.draw.circle(icon, (24, 20, 42), (16, 16), 15)
    pygame.draw.circle(icon, (168, 120, 255), (16, 16), 15, 2)
    pygame.draw.circle(icon, (92, 214, 240), (16, 16), 8, 1)
    for k in range(3):
        ang = k * math.tau / 3 - math.pi / 2
        x = 16 + math.cos(ang) * 9
        y = 16 + math.sin(ang) * 9
        pygame.draw.circle(icon, (240, 220, 255), (int(x), int(y)), 2)
    pygame.draw.circle(icon, (255, 248, 220), (16, 16), 2)
    return icon


class Game:
    def __init__(self, spells_dir: str | None = None):
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_icon(_make_icon())
        self._focus_window()
        self.clock = pygame.time.Clock()
        self.world_rect = pygame.Rect(WORLD_X, WORLD_Y, WORLD_W, WORLD_H)
        self.spells_dir = spells_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spells")
        os.makedirs(self.spells_dir, exist_ok=True)
        self.save_path = os.path.join(os.path.dirname(self.spells_dir), "savegame.json")

        pygame.key.set_repeat(280, 32)

        self.audio = Audio()
        self._mana_warn_at = -10.0

        self.spellbook = Spellbook()
        self.spells = []
        self.selected_index = 0
        self.state = "playing"
        self.running = True
        self.debug = False

        self.keys = {k: False for k in ("w", "a", "s", "d", "up", "down", "left", "right")}
        self._down_keys: set[int] = set()
        self.focused = True
        self.mouse_pos = (WINDOW_W // 2, WINDOW_H // 2)
        self.mouse_world = Vector2(WORLD_W / 2, WORLD_H / 2)
        self.mouse_held = False

        self.time = 0.0
        self.accum = 0.0
        self.shake_amp = 0.0
        self.shake_offset = (0, 0)
        self.hurt_flash = 0.0
        self.cast_damage = 0.0
        self.total_damage = 0.0
        self.toasts: list[list] = []
        self.pause_buttons: dict[str, pygame.Rect] = {}
        self.last_toggle = 0.0

        # Progression -------------------------------------------------
        self.level = 1
        self.xp = 0
        self.xp_to_next = 60
        self.unlocked_canvases: set[str] = {"small"}
        self.quest_index = 0
        self.quest_completed: set[str] = set()
        self.quest_baseline: dict[str, float] = {}
        self.tutorial_seen = False
        self._overkill_this_cast = False

        self.stats = {
            "casts": 0,
            "kills": 0,
            "best_cast_damage": 0,
            "shield_blocks": 0,
            "spells_saved": 0,
            "weaves_saved": 0,
            "code_saved": 0,
            "weave_cycles": 0,
            "big_weaves": 0,
            "vortex_casts": 0,
            "overkills": 0,
            "quests_done": 0,
            "deaths": 0,
            "resets": 0,
            "burned": 0,
            "evaporated": 0,
            "frozen": 0,
            "melted": 0,
            "dissolved": 0,
            "cooled": 0,
            "oil_ignited": 0,
        }
        self._load_progress()

        self.renderer = WorldRenderer()
        self.runtime = SpellRuntime(self)
        self.editor = Editor(self)
        self.weave = WeaveEditor(self)
        self.seed = random.randint(1, 99999)
        self.reset_arena(self.seed, announce=False)
        self.reload_spells()
        self.state = "tutorial" if not self.tutorial_seen else "playing"
        self.toast("Welcome, wizard. H = language, G = weave canvas.", ACCENT, 5.0)

    # ------------------------------------------------------------------
    # Progression, quests and level
    # ------------------------------------------------------------------
    @property
    def current_quest(self):
        if 0 <= self.quest_index < len(CHALLENGES):
            return CHALLENGES[self.quest_index]
        return None

    @property
    def quest_progress(self) -> float:
        quest = self.current_quest
        if quest is None:
            return 0.0
        base = self.quest_baseline.get(quest.id, 0.0)
        value = float(self.stats.get(quest.stat, 0.0)) - base
        return max(0.0, min(float(quest.goal), value))

    @property
    def quest_total(self) -> int:
        return len(CHALLENGES)

    @staticmethod
    def _xp_needed(level: int) -> int:
        return 60 + max(0, level - 1) * 45

    @staticmethod
    def _max_mana_for_level(level: int) -> int:
        return max(1, int(round(1000.0 * (1.10 ** (max(1, level) - 1)))))

    def _start_quest(self, index: int, reset_baseline: bool = True) -> None:
        self.quest_index = max(0, min(index, len(CHALLENGES)))
        quest = self.current_quest
        if quest is not None:
            value = float(self.stats.get(quest.stat, 0.0))
            if reset_baseline:
                self.quest_baseline[quest.id] = value
            else:
                self.quest_baseline.setdefault(quest.id, value)

    def _load_progress(self) -> None:
        data = None
        try:
            if os.path.exists(self.save_path):
                with open(self.save_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            self.level = max(1, int(data.get("level", 1)))
            self.xp = max(0, int(data.get("xp", 0)))
            self.xp_to_next = max(1, int(data.get("xp_to_next", self._xp_needed(self.level))))
            raw_unlocked = data.get("unlocked", ["small"])
            if isinstance(raw_unlocked, list):
                self.unlocked_canvases = {"small"} | {
                    key for key in raw_unlocked if key in ("medium", "large")}
            raw_stats = data.get("stats", {})
            if isinstance(raw_stats, dict):
                for key, value in raw_stats.items():
                    if key in self.stats and isinstance(value, (int, float)):
                        self.stats[key] = value
            raw_done = data.get("quest_completed", [])
            if isinstance(raw_done, list):
                self.quest_completed = {str(q) for q in raw_done}
            raw_base = data.get("quest_baseline", {})
            if isinstance(raw_base, dict):
                self.quest_baseline = {}
                for key, value in raw_base.items():
                    if isinstance(value, (int, float)):
                        self.quest_baseline[str(key)] = float(value)
            self.tutorial_seen = bool(data.get("tutorial_seen", False))
            self._start_quest(int(data.get("quest_index", 0)), reset_baseline=False)
        else:
            self._start_quest(0)

    def _save_progress(self) -> None:
        data = {
            "version": 1,
            "level": self.level,
            "xp": self.xp,
            "xp_to_next": self.xp_to_next,
            "unlocked": sorted(self.unlocked_canvases),
            "quest_index": self.quest_index,
            "quest_completed": sorted(self.quest_completed),
            "quest_baseline": self.quest_baseline,
            "tutorial_seen": self.tutorial_seen,
            "stats": {k: v for k, v in self.stats.items() if isinstance(v, (int, float))},
        }
        try:
            with open(self.save_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
        except OSError:
            pass

    def gain_xp(self, amount: int, reason: str = "") -> None:
        if amount <= 0:
            return
        self.xp += int(amount)
        levelled = False
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.xp_to_next = self._xp_needed(self.level)
            self.player.max_mana = float(self._max_mana_for_level(self.level))
            self.player.mana = self.player.max_mana
            levelled = True
            self.toast(f"Level {self.level}! Max mana {int(self.player.max_mana)}.",
                       (240, 210, 120), 4.5)
            self.rings.append(Ring(self.player.x, self.player.y, 8, 90, 0.8,
                                   (240, 210, 120), 3))
            self.particles.burst(self.player.x, self.player.y, "light", 28,
                                 speed=120, life=0.9)
            self.audio.play("heal", 0.7)
        if reason:
            self.add_floater(self.player.x, self.player.y - 26,
                             f"+{int(amount)} XP", (240, 210, 120), 12, 1.0)
        if levelled:
            self._save_progress()

    def _dismiss_tutorial(self) -> None:
        self.tutorial_seen = True
        self.state = "playing"
        self._save_progress()
        self.audio.play("ui", 0.35)
        quest = self.current_quest
        if quest is not None:
            self.toast(f"Quest 1/{self.quest_total}: {quest.title}", ACCENT, 4.0)

    # ------------------------------------------------------------------
    # Spellbook
    # ------------------------------------------------------------------
    @property
    def selected_spell(self):
        if not self.spells:
            return None
        idx = max(0, min(len(self.spells) - 1, self.selected_index))
        return self.spells[idx]

    @property
    def current_spell(self):
        return self.selected_spell

    @property
    def selected_element(self) -> str:
        spell = self.selected_spell
        return spell.element if spell else "arcane"

    def reload_spells(self) -> None:
        old_name = self.selected_spell.name if self.selected_spell else None
        self.spellbook = load_spellbook(self.spells_dir)
        visible: list = []
        for spell in self.spellbook.as_list():
            if spell.path.lower().endswith(".weave"):
                try:
                    graph = load_weave(spell.path)
                except SpellError:
                    continue
                if graph.canvas not in self.unlocked_canvases:
                    continue
            visible.append(spell)
        self.spells = visible
        if old_name:
            for i, spell in enumerate(self.spells):
                if spell.name == old_name:
                    self.selected_index = i
                    break
        if self.spells:
            self.selected_index = max(0, min(len(self.spells) - 1, self.selected_index))
        else:
            self.selected_index = 0
        if self.spellbook.errors:
            err = self.spellbook.errors[0]
            self.toast(f"Spell error: {err.filename}:{err.line} - {err.message}", RED, 6.0)

    def next_challenge(self):
        return self.current_quest

    # ------------------------------------------------------------------
    # Arena
    # ------------------------------------------------------------------
    def reset_arena(self, seed: int | None = None, announce: bool = True) -> None:
        if seed is None:
            seed = random.randint(1, 99999)
        self.seed = seed
        self.world = World(seed=seed)
        spawns = self.world.build_arena()
        self._last_world_stats = {name: 0.0 for name in self.world.stats}
        self.spawn_point = spawns["player"]
        self.player = Player(*spawns["player"])
        self.player.max_mana = float(self._max_mana_for_level(self.level))
        self.player.mana = self.player.max_mana
        self.enemies = [Dummy(*pos) for pos in spawns["dummies"]]
        self.enemies += [make_stalker(*pos) for pos in spawns["stalkers"]]
        self.enemies += [make_eye(*pos) for pos in spawns["eyes"]]
        self.projectiles: list[Projectile] = []
        self.fields = []
        self.vortices = []
        self.shields = []
        self.particles = ParticleSystem()
        self.floaters: list[FloatingText] = []
        self.rings: list[Ring] = []
        self.beams = []
        self.timed_tiles: list[list] = []
        self.accum = 0.0
        self.cast_damage = 0.0
        if announce:
            self.stats["resets"] += 1
            self.toast("The arena is remade.", ACCENT)

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------
    def toast(self, text: str, color=ACCENT, duration: float = 3.0) -> None:
        self.toasts.append([text, color, duration, duration])
        while len(self.toasts) > 4:
            self.toasts.pop(0)

    def shake(self, amount: float) -> None:
        self.shake_amp = min(16.0, self.shake_amp + amount)

    def add_floater(self, x, y, text, color, size=14, life=0.8) -> None:
        if len(self.floaters) > 80:
            self.floaters.pop(0)
        self.floaters.append(FloatingText(x, y, text, color, size, life))

    def add_timed_tile(self, x: int, y: int, mat: int, life: float) -> None:
        if len(self.timed_tiles) < 900:
            self.timed_tiles.append([x, y, mat, life, life])

    def stat(self, name: str) -> float:
        return float(self.stats.get(name, 0))

    # ------------------------------------------------------------------
    # Combat helpers
    # ------------------------------------------------------------------
    def hurt_player(self, amount: float, source: str = "") -> None:
        p = self.player
        if p.invuln > 0 or p.hp <= 0:
            return
        p.take_damage(amount)
        p.invuln = 0.45
        self.hurt_flash = max(self.hurt_flash, 0.55)
        self.shake(3.0)
        self.audio.play("hit", 0.5)
        self.add_floater(p.x, p.y - 16, f"-{int(amount)}", (255, 120, 120), 15)
        if p.hp <= 0:
            self.player_died()

    def player_died(self) -> None:
        p = self.player
        self.stats["deaths"] += 1
        self.toast("You are unmade. The circle reforms you.", RED, 4.0)
        self.particles.burst(p.x, p.y, "dark", 30, speed=130, life=0.9)
        p.x, p.y = self.spawn_point
        p.hp = p.max_hp
        p.mana = p.max_mana
        p.alive = True
        p.invuln = 2.0
        p.dash_v.update(0, 0)
        p.burn = p.poison = p.chill = 0.0
        # Clear hostile bolts so respawning is not instantly lethal.
        self.projectiles = [pr for pr in self.projectiles if not pr.hostile]

    def on_enemy_killed(self, enemy) -> None:
        if enemy.respawn_at > 0:
            return
        enemy.respawn_at = self.time + (3.5 if isinstance(enemy, Dummy) else 8.0)
        enemy.alive = False
        enemy.hp = 0
        if not isinstance(enemy, Dummy):
            self.stats["kills"] += 1
            self.gain_xp(18 if enemy.ranged else 12)
        self.particles.burst(enemy.x, enemy.y, "arcane", 22, speed=110, life=0.7)
        self.rings.append(Ring(enemy.x, enemy.y, 3, 42, 0.4, (190, 140, 255), 2))
        self.shake(2.0)
        self.audio.play("boom", 0.3)

    def spawn_hostile_bolt(self, x, y, direction, speed=180, damage=8,
                           element="dark") -> None:
        self.projectiles.append(Projectile(
            x, y, direction.x * speed, direction.y * speed, 5.0, element, damage,
            owner=None, hostile=True, life=4.5, power=0.6,
        ))

    # ------------------------------------------------------------------
    # Casting
    # ------------------------------------------------------------------
    def aim_point(self) -> Vector2:
        delta = self.mouse_world - self.player.pos
        max_range = 62 * TILE
        if delta.length() > max_range:
            delta.scale_to_length(max_range)
        return self.player.pos + delta

    def try_cast(self) -> bool:
        spell = self.selected_spell
        if spell is None:
            return False
        p = self.player
        if p.cooldowns.get(spell.name, 0.0) > 0:
            return False
        if p.mana < spell.mana:
            now = time.perf_counter()
            if now - self._mana_warn_at > 1.1:
                self._mana_warn_at = now
                self.toast("Not enough mana.", RED, 1.2)
                self.audio.play("error", 0.6)
            return False
        origin = p.pos
        point = self.aim_point()
        aim = point - origin
        if aim.length_squared() < 1:
            aim = Vector2(1, 0)
        p.aim = aim.normalize()
        p.mana -= spell.mana
        p.cooldowns[spell.name] = spell.cooldown
        self.stats["casts"] += 1
        self.cast_damage = 0.0
        self._overkill_this_cast = False
        p.cast_flash = 0.2
        self._cast_sound(spell.element)
        self.runtime.execute(spell.program, p, origin, p.aim, point)
        return True

    def _cast_sound(self, elem: str) -> None:
        if elem in ("fire", "earth"):
            self.audio.play("boom", 0.45)
        elif elem in ("ice", "water"):
            self.audio.play("freeze", 0.5)
        elif elem == "lightning":
            self.audio.play("zap", 0.5)
        else:
            self.audio.play("cast", 0.5)
        self.audio.play("cast", 0.22)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _hotkey(self, name: str, cooldown: float = 0.3) -> bool:
        now = time.perf_counter()
        if now - getattr(self, "_last_hotkey_" + name, -10.0) < cooldown:
            return False
        setattr(self, "_last_hotkey_" + name, now)
        return True

    @staticmethod
    def _focus_window() -> None:
        """Make sure the SDL window owns the keyboard on Windows."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = pygame.display.get_wm_info().get("window")
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 5)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        except Exception:
            pass

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            if event.type == pygame.WINDOWFOCUSLOST:
                self.focused = False
                self._clear_keys()
                self._down_keys.clear()
                continue
            if event.type == pygame.WINDOWFOCUSGAINED:
                self.focused = True
                continue
            if event.type == pygame.MOUSEBUTTONDOWN:
                self.focused = True
            if event.type == pygame.MOUSEMOTION:
                self.mouse_pos = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.mouse_held = False
            if self.weave.open:
                self.weave.handle_event(event)
                continue
            if self.editor.open:
                self.editor.handle_event(event)
                continue
            self._handle_game_event(event)
        if self.state == "forge" and not self.weave.open:
            self.state = "playing"
        if self.state == "editor" and not self.editor.open:
            self.state = "playing"

    def _handle_game_event(self, event: pygame.event.Event) -> None:
        if self.state == "tutorial":
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self._dismiss_tutorial()
            return
        if event.type == pygame.KEYDOWN:
            key = event.key
            is_repeat = key in self._down_keys
            self._down_keys.add(key)
            if self.state == "help":
                if key in (pygame.K_ESCAPE, pygame.K_h, pygame.K_F1) and not is_repeat:
                    self.state = "playing"
                return
            if self.state == "challenges":
                if key in (pygame.K_ESCAPE, pygame.K_c) and not is_repeat:
                    self.state = "playing"
                return
            if self.state == "spellbook":
                if key in (pygame.K_ESCAPE, pygame.K_TAB) and not is_repeat:
                    self.state = "playing"
                elif pygame.K_1 <= key <= pygame.K_9 and not is_repeat:
                    self.selected_index = min(key - pygame.K_1, len(self.spells) - 1)
                return
            if self.state == "paused":
                if key == pygame.K_ESCAPE and not is_repeat:
                    self.state = "playing"
                return
            if self.state != "playing":
                return
            if key == pygame.K_ESCAPE and self._hotkey("pause"):
                self.state = "paused"
                self._clear_keys()
                self.audio.play("ui", 0.3)
            elif key in (pygame.K_h, pygame.K_F1) and self._hotkey("help"):
                self.state = "help"
                self._clear_keys()
                self.audio.play("ui", 0.3)
            elif key == pygame.K_c and self._hotkey("challenges"):
                self.state = "challenges"
                self._clear_keys()
                self.audio.play("ui", 0.3)
            elif key == pygame.K_TAB and self._hotkey("book"):
                self.state = "spellbook"
                self._clear_keys()
                self.audio.play("ui", 0.3)
            elif key == pygame.K_e and self._hotkey("editor"):
                self.open_editor()
            elif key == pygame.K_g and self._hotkey("weave"):
                self.open_weave()
            elif key == pygame.K_m and self._hotkey("mute"):
                self.audio.muted = not self.audio.muted
                self.toast("Sound muted." if self.audio.muted else "Sound on.", ACCENT, 1.4)
                self.audio.play("ui", 0.35)
            elif key == pygame.K_F2 and self._hotkey("reset"):
                self.reset_arena()
            elif key == pygame.K_F3 and self._hotkey("debug"):
                self.debug = not self.debug
            elif pygame.K_1 <= key <= pygame.K_9:
                idx = key - pygame.K_1
                if idx < len(self.spells):
                    self.selected_index = idx
                    self.audio.play("ui", 0.25)
                else:
                    self.toast("That spell slot is empty.", RED, 1.0)
                    self.audio.play("error", 0.4)
            else:
                self._set_move_key(key, True)
            return

        if event.type == pygame.KEYUP:
            self._down_keys.discard(event.key)
            self._set_move_key(event.key, False)
            return

        if event.type == pygame.MOUSEWHEEL:
            if self.state == "spellbook" or self.state == "playing":
                if self.spells:
                    self.selected_index = (self.selected_index - event.y) % len(self.spells)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if self.state == "paused":
                for name, rect in self.pause_buttons.items():
                    if rect.collidepoint(pos):
                        if name == "resume":
                            self.state = "playing"
                        elif name == "reset":
                            self.state = "playing"
                            self.reset_arena()
                        elif name == "quit":
                            self.running = False
                        return
            elif self.state == "spellbook":
                idx = self._spellbook_card_at(pos)
                if idx is not None:
                    self.selected_index = idx
                    self.audio.play("ui", 0.25)
                elif not pygame.Rect(70, 48, WINDOW_W - 140, WINDOW_H - 96).collidepoint(pos):
                    self.state = "playing"
                return
            elif self.state == "playing":
                if self.world_rect.collidepoint(pos):
                    self.mouse_held = True
                    self.try_cast()
                    return
                idx = self._spell_row_at(pos)
                if idx is not None:
                    self.selected_index = idx
            return

    def _set_move_key(self, key: int, down: bool) -> None:
        mapping = {
            pygame.K_w: "w", pygame.K_a: "a", pygame.K_s: "s", pygame.K_d: "d",
            pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left",
            pygame.K_RIGHT: "right",
        }
        if key in mapping:
            self.keys[mapping[key]] = down

    def _clear_keys(self) -> None:
        for k in self.keys:
            self.keys[k] = False
        self.mouse_held = False

    def _spell_row_at(self, pos) -> int | None:
        start_x = PANEL_X + 6
        start_y = SLOTS_Y + 24
        if pos[0] < start_x or pos[0] > PANEL_X + PANEL_W - 6:
            return None
        rel = pos[1] - start_y
        if rel < 0:
            return None
        idx = int(rel // SLOT_ROW_H)
        if 0 <= idx < min(9, len(self.spells)) and rel % SLOT_ROW_H <= 25:
            return idx
        return None

    def _spellbook_card_at(self, pos) -> int | None:
        outer = pygame.Rect(70, 48, WINDOW_W - 140, WINDOW_H - 96)
        cols = 3
        card_w = (outer.w - 56) // cols
        card_h = 84
        x0 = outer.x + 20
        y0 = outer.y + 54
        for i in range(len(self.spells)):
            col = i % cols
            row = i // cols
            rect = pygame.Rect(x0 + col * (card_w + 8), y0 + row * (card_h + 8), card_w, card_h)
            if rect.collidepoint(pos):
                return i
        return None

    def open_editor(self) -> None:
        spell = self.selected_spell
        if spell and spell.path.lower().endswith(".weave"):
            self.toast("That is a woven spell. Press G to edit its canvas.", ACCENT, 3.0)
            self.audio.play("error", 0.4)
            return
        self.state = "editor"
        self._clear_keys()
        self.editor.open_editor()

    def open_weave(self) -> None:
        self.state = "forge"
        self._clear_keys()
        spell = self.selected_spell
        if spell and spell.path.lower().endswith(".weave"):
            try:
                graph = load_weave(spell.path)
                self.weave.open_editor(graph, spell.path, spell.name)
            except SpellError as exc:
                self.toast(f"Cannot open weave: {exc.message}", RED, 3.0)
                self.weave.open_editor()
        else:
            self.weave.open_editor()
        self.audio.play("ui", 0.35)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.time += dt
        for toast in self.toasts:
            toast[2] -= dt
        self.toasts = [t for t in self.toasts if t[2] > 0]
        self.hurt_flash = max(0.0, self.hurt_flash - dt * 2.2)
        self.shake_amp = max(0.0, self.shake_amp - dt * 26)
        if self.shake_amp > 0.1:
            self.shake_offset = (random.uniform(-1, 1) * self.shake_amp,
                                 random.uniform(-1, 1) * self.shake_amp)
        else:
            self.shake_offset = (0, 0)

        if self.state == "tutorial":
            return
        if self.state == "forge":
            self.weave.update(dt)
            if not self.weave.open:
                self.state = "playing"
            return
        if self.state == "editor":
            self.editor.update(dt)
            if not self.editor.open:
                self.state = "playing"
            return
        if self.state != "playing":
            return

        # Mouse world position.
        mx, my = pygame.mouse.get_pos()
        self.mouse_pos = (mx, my)
        wx = max(0, min(WORLD_W - 1, mx - self.world_rect.x))
        wy = max(0, min(WORLD_H - 1, my - self.world_rect.y))
        self.mouse_world.update(wx, wy)

        self._update_world(dt)
        self._update_player(dt)
        self._update_enemies(dt)
        self._update_projectiles(dt)
        self._update_fields(dt)
        self._update_vortices(dt)
        self._update_shields(dt)
        self._update_timed(dt)
        self._update_ambient(dt)

        for name, value in self.world.stats.items():
            prev = self._last_world_stats.get(name, 0.0)
            if value > prev:
                self.stats[name] = self.stats.get(name, 0.0) + (value - prev)
                self._last_world_stats[name] = value
            elif value < prev:
                self._last_world_stats[name] = value
        self._update_quests()

        if self.mouse_held:
            self.try_cast()

    def _update_world(self, dt: float) -> None:
        self.accum += dt
        steps = 0
        while self.accum >= DT and steps < 2:
            self.world.step(DT)
            self.accum -= DT
            steps += 1
        self.renderer.update(dt)

    def _update_player(self, dt: float) -> None:
        p = self.player
        aim = self.mouse_world - p.pos
        if aim.length_squared() > 1:
            p.aim = aim.normalize()
        p.update(dt, self)
        p.status_tick(dt, self.world, self)
        if p.burn > 0 and random.random() < dt * 5:
            self.particles.burst(p.x, p.y, "fire", 1, speed=14)
        if p.dash_v.length_squared() > 120 * 120 and random.random() < dt * 40:
            self.particles.trail(p.x, p.y, p.dash_element)
        if p.hp <= 0:
            self.player_died()

    def _update_enemies(self, dt: float) -> None:
        for e in list(self.enemies):
            if not e.alive:
                if e.respawn_at and self.time >= e.respawn_at:
                    e.alive = True
                    e.hp = e.max_hp
                    e.x, e.y = e.spawn
                    e.burn = e.poison = e.chill = e.wet = 0.0
                    e.respawn_at = 0.0
                    e.hit_flash = 0.0
                    self.particles.burst(e.x, e.y, "arcane", 14, speed=60, life=0.5)
                continue
            e.status_tick(dt, self.world, self)
            if not e.alive:
                self.on_enemy_killed(e)
                continue
            e.update(dt, self)

    def _update_projectiles(self, dt: float) -> None:
        alive = []
        for pr in self.projectiles:
            if pr.dead:
                continue
            pr.life -= dt
            if pr.life <= 0:
                pr.dead = True
                self._expire_projectile(pr)
                continue
            # Homing toward the closest enemy.
            if pr.homing > 0 and not pr.hostile:
                target = None
                best = 14 * TILE
                for e in self.enemies:
                    if not e.alive:
                        continue
                    d = math.hypot(e.x - pr.x, e.y - pr.y)
                    if d < best:
                        best = d
                        target = e
                if target is not None:
                    desired = Vector2(target.x - pr.x, target.y - pr.y)
                    if desired.length_squared() > 0:
                        desired.scale_to_length(math.hypot(pr.vx, pr.vy))
                        speed = max(1.0, math.hypot(pr.vx, pr.vy))
                        turn = min(1.0, pr.homing * dt * 0.9)
                        newv = Vector2(pr.vx, pr.vy).lerp(desired, turn)
                        if newv.length_squared() > 0:
                            newv.scale_to_length(speed)
                        pr.vx, pr.vy = newv.x, newv.y

            speed = math.hypot(pr.vx, pr.vy)
            travel = speed * dt
            steps = max(1, int(travel // 3) + 1)
            sx = pr.vx * dt / steps
            sy = pr.vy * dt / steps
            for _ in range(steps):
                pr.x += sx
                pr.y += sy
                if pr.x < 0 or pr.y < 0 or pr.x >= WORLD_W or pr.y >= WORLD_H:
                    pr.dead = True
                    break
                if self.world.solid_at_px(pr.x, pr.y):
                    self._projectile_world_hit(pr)
                    break
                if pr.hostile:
                    if self._shield_blocks(pr):
                        break
                    p = self.player
                    if (pr.x - p.x) ** 2 + (pr.y - p.y) ** 2 <= (p.r + pr.r) ** 2:
                        self.hurt_player(pr.damage, "bolt")
                        pr.dead = True
                        break
                else:
                    hit = False
                    for e in self.enemies:
                        if not e.alive or id(e) in pr.hits:
                            continue
                        if (pr.x - e.x) ** 2 + (pr.y - e.y) ** 2 <= (e.r + pr.r) ** 2:
                            pr.hits.add(id(e))
                            self.runtime._damage_one(e, pr.damage, pr.element, self.player, 1.0)
                            self.particles.burst(pr.x, pr.y, pr.element, 6, speed=60, life=0.4)
                            self._run_on_hit(pr, Vector2(pr.x, pr.y))
                            if pr.pierce > 0:
                                pr.pierce -= 1
                            else:
                                pr.dead = True
                            hit = True
                            break
                    if hit:
                        break
            if pr.dead:
                continue
            pr.trail -= dt
            if pr.trail <= 0:
                pr.trail = 0.02
                self.particles.trail(pr.x, pr.y, pr.element, 1.6)
            alive.append(pr)
        self.projectiles = [p for p in self.projectiles if not p.dead]

    def _run_on_hit(self, pr: Projectile, point: Vector2) -> None:
        if pr.on_hit:
            speed = math.hypot(pr.vx, pr.vy)
            direction = Vector2(pr.vx, pr.vy) / speed if speed > 0.001 else Vector2(1, 0)
            self.runtime.execute(pr.on_hit, self.player, point, direction, point, 1)

    def _projectile_world_hit(self, pr: Projectile) -> None:
        point = Vector2(pr.x, pr.y)
        self.runtime.impact(point, pr.element, pr.power * 0.85,
                            max(0.55, pr.size * 0.55), self.player)
        self._run_on_hit(pr, point)
        pr.dead = True

    def _expire_projectile(self, pr: Projectile) -> None:
        point = Vector2(pr.x, pr.y)
        if pr.on_expire:
            speed = math.hypot(pr.vx, pr.vy)
            direction = Vector2(pr.vx, pr.vy) / speed if speed > 0.001 else Vector2(1, 0)
            self.runtime.execute(pr.on_expire, self.player, point, direction, point, 1)
        else:
            self.runtime.impact(point, pr.element, pr.power * 0.55,
                                max(0.5, pr.size * 0.45), self.player)

    def _shield_blocks(self, pr: Projectile) -> bool:
        p = self.player
        for shield in list(self.shields):
            if (pr.x - p.x) ** 2 + (pr.y - p.y) ** 2 <= (shield.radius + pr.r) ** 2:
                pr.dead = True
                shield.flash = 0.3
                shield.power -= 0.18
                self.stats["shield_blocks"] += 1
                self.particles.burst(pr.x, pr.y, shield.element, 10, speed=80, life=0.4)
                self.rings.append(Ring(p.x, p.y, shield.radius, shield.radius + 8, 0.2,
                                       ELEMENTS[shield.element]["color"], 2))
                if shield.power <= 0:
                    self.shields.remove(shield)
                return True
        return False

    def _update_fields(self, dt: float) -> None:
        kept = []
        for f in self.fields:
            f.life -= dt
            if f.life <= 0:
                continue
            f.tick -= dt
            if f.tick <= 0:
                f.tick = 0.3
                f.ticks += 1
                radius_tiles = (f.radius / TILE) * 0.8
                self.runtime.impact(Vector2(f.x, f.y), f.element, f.power * 0.5,
                                    radius_tiles, self.player,
                                    splat=(f.ticks % 2 == 0), damage_scale=0.55)
                self.particles.burst(f.x, f.y, f.element, 2, speed=40, life=0.4)
            kept.append(f)
        self.fields = kept

    def _update_vortices(self, dt: float) -> None:
        kept = []
        for v in self.vortices:
            v.life -= dt
            v.angle += dt * 4.2
            v.phase += dt
            if v.life <= 0:
                self.particles.burst(v.x, v.y, v.element, 18, speed=95, life=0.55)
                continue
            # Drag everything nearby toward the eye while spinning it.
            for e in self.enemies:
                if not e.alive:
                    continue
                dx = v.x - e.x
                dy = v.y - e.y
                d = math.hypot(dx, dy)
                reach = v.radius * 1.2 + e.r
                if d < 1.0 or d > reach:
                    continue
                ux, uy = dx / d, dy / d
                inward = v.pull * 78.0
                tangent = v.pull * 92.0 * v.spin
                sx = (ux * inward - uy * tangent) * dt
                sy = (uy * inward + ux * tangent) * dt
                e.x, e.y = move_circle(self.world, e.x, e.y, e.r, sx, sy)
            v.tick -= dt
            if v.tick <= 0.0:
                v.tick = 0.26
                for e in list(self.enemies):
                    if not e.alive:
                        continue
                    if math.hypot(e.x - v.x, e.y - v.y) <= v.radius + e.r:
                        dmg = 2.1 * v.power * ELEMENTS[v.element]["damage"]
                        self.runtime._damage_one(e, dmg, v.element, self.player, 1.0)
                for _ in range(3):
                    a = random.random() * math.tau
                    rr = v.radius * (0.35 + random.random() * 0.75)
                    self.particles.burst(v.x + math.cos(a) * rr,
                                         v.y + math.sin(a) * rr,
                                         v.element, 1, speed=30, life=0.45, size=2)
            kept.append(v)
        self.vortices = kept

    def _update_shields(self, dt: float) -> None:
        for s in self.shields:
            s.life -= dt
            s.flash = max(0.0, s.flash - dt)
        self.shields = [s for s in self.shields if s.life > 0 and s.power > 0]

    def _update_timed(self, dt: float) -> None:
        kept = []
        for entry in self.timed_tiles:
            x, y, mat, life, total = entry
            life -= dt
            if life <= 0:
                if self.world.get(x, y) == mat:
                    self.world.set(x, y, EMPTY)
                    self.particles.burst(x * TILE, y * TILE, "arcane", 2, speed=20, life=0.35)
                continue
            entry[3] = life
            kept.append(entry)
        self.timed_tiles = kept

    def _update_ambient(self, dt: float) -> None:
        self.particles.update(dt)
        kept = []
        for f in self.floaters:
            f.life -= dt
            f.y += f.vy * dt
            f.vy *= max(0.0, 1 - dt * 2.2)
            if f.life > 0:
                kept.append(f)
        self.floaters = kept
        for r in self.rings:
            r.life -= dt
        self.rings = [r for r in self.rings if r.life > 0]
        for b in self.beams:
            b.life -= dt
        self.beams = [b for b in self.beams if b.life > 0]

    def _update_quests(self) -> None:
        while True:
            quest = self.current_quest
            if quest is None:
                break
            base = self.quest_baseline.get(quest.id, 0.0)
            value = float(self.stats.get(quest.stat, 0.0)) - base
            if value < quest.goal:
                break
            self.quest_completed.add(quest.id)
            self.stats["quests_done"] = len(self.quest_completed)
            self.quest_index += 1
            self.gain_xp(quest.reward_xp, "quest")
            self.toast(f"Quest complete: {quest.title} (+{quest.reward_xp} XP)",
                       (240, 210, 120), 5.0)
            if quest.unlock:
                self.unlocked_canvases.add(quest.unlock)
                label = {"medium": "MEDIUM", "large": "HIGH"}.get(
                    quest.unlock, quest.unlock.upper())
                self.toast(f"{label} canvas unlocked!", ACCENT, 5.0)
                self.reload_spells()
            self.shake(2.5)
            self.audio.play("heal", 0.65)
            nxt = self.current_quest
            if nxt is not None:
                self.quest_baseline[nxt.id] = float(self.stats.get(nxt.stat, 0.0))
            self._save_progress()
            if nxt is None:
                self.toast("All quests complete. The sandbox is yours.",
                           ACCENT, 6.0)
                break

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------
    def draw(self) -> None:
        self.screen.fill(BG)
        if self.weave.open:
            self.weave.draw(self.screen)
            if not self.focused:
                draw_focus_hint(self.screen)
            return
        if self.editor.open:
            self.editor.draw(self.screen)
            if not self.focused:
                draw_focus_hint(self.screen)
            return
        self.renderer.render(self.screen, self)
        if self.hurt_flash > 0:
            layer = pygame.Surface((WORLD_W, WORLD_H), pygame.SRCALPHA)
            layer.fill((180, 20, 20, int(80 * self.hurt_flash)))
            self.screen.blit(layer, self.world_rect.topleft)
        draw_hud(self.screen, self)
        if not self.focused:
            draw_focus_hint(self.screen)
        if self.state == "help":
            draw_help(self.screen, self)
        elif self.state == "challenges":
            draw_challenges(self.screen, self)
        elif self.state == "spellbook":
            draw_spellbook(self.screen, self)
        elif self.state == "paused":
            draw_pause(self.screen, self)
        elif self.state == "tutorial":
            draw_tutorial(self.screen, self)

    # ------------------------------------------------------------------
    def run(self) -> None:
        last = time.perf_counter()
        refreshed = False
        while self.running:
            now = time.perf_counter()
            dt = min(0.05, now - last)
            last = now
            self.handle_events()
            if not self.running:
                break
            self.update(dt)
            self.draw()
            pygame.display.flip()
            if not refreshed:
                self._focus_window()
                refreshed = True
            self.clock.tick(FPS)
        self._save_progress()
        pygame.quit()
