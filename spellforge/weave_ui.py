"""Canvas editor for graph-woven spells (prototype: fire, water, earth, air).

The player places elemental runes, drags curved arrows between them and pays
for every rune and relation out of a canvas-sized mana budget.  The graph is
resolved by :mod:`spellforge.weave` into a normal spell, so the rest of the
game (spellbook, casting, world simulation) does not need to care where the
spell came from.
"""

from __future__ import annotations

import math
import os
import re

import pygame

from .config import (ACCENT, BG, BG_PANEL, BG_PANEL_LIGHT, BORDER, ELEMENTS, GOLD,
                     GREEN, RED, TEXT, TEXT_DIM, TEXT_FAINT, WINDOW_H, WINDOW_W)
from .gfx import bar, draw_text, panel, wrap
from .weave import (BASE_COST, BEND_MAX, BEND_MIN, CANVAS, ELEMENTS4, NODE_MAX,
                    NODE_MIN, WeaveGraph, WeaveLink, WeaveNode, link_cost,
                    load_weave, node_radius, save_weave, tornado_graph)

OUTER = pygame.Rect(16, 16, WINDOW_W - 32, WINDOW_H - 32)
PALETTE = pygame.Rect(28, 84, 186, 560)
CANVAS_AREA = pygame.Rect(228, 84, 890, 560)
INFO = pygame.Rect(1132, 84, 280, 560)
STATUS = pygame.Rect(228, 652, 890, 36)

TIER_RECTS = {
    "small": pygame.Rect(300, 28, 96, 30),
    "medium": pygame.Rect(404, 28, 96, 30),
    "large": pygame.Rect(508, 28, 96, 30),
}
DEMO_RECT = pygame.Rect(624, 28, 128, 30)
SAVE_RECT = pygame.Rect(1104, 28, 92, 30)
CLEAR_RECT = pygame.Rect(1204, 28, 92, 30)
CLOSE_RECT = pygame.Rect(1304, 28, 92, 30)
TAB_RUNES = pygame.Rect(40, 96, 76, 22)
TAB_SPELLS = pygame.Rect(120, 96, 84, 22)
RUNE_Y = 136
RUNE_STEP = 56
RUNE_H = 48
SPELL_Y = 136
SPELL_STEP = 48
SPELL_H = 42

SHAPE_LABEL = {
    "vortex": "VORTEX",
    "steam": "STEAM VORTEX",
    "bolt": "BOLT",
    "beam": "LANCE",
    "volley": "VOLLEY",
    "wall": "WALL",
    "burst": "BURST",
    "nested": "NESTED SPELL",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _mix(a, b, t: float = 0.5):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _dark(col, f: float = 0.22):
    return tuple(max(8, int(c * f)) for c in col)


class WeaveEditor:
    def __init__(self, game):
        self.game = game
        self.open = False
        self.graph = WeaveGraph(canvas="medium")
        self.active_element: str | None = "air"
        self.active_spell: str | None = None
        self.palette_mode = "runes"
        self.spell_scroll = 0
        self.selected_id: int | None = None
        self.hover_id: int | None = None
        self.hover_link: WeaveLink | None = None
        self.mouse = (0, 0)
        self.time = 0.0

        self.drag_node: int | None = None
        self.drag_offset = (0.0, 0.0)
        self.drag_origin = (0.0, 0.0)

        self.link_src: int | None = None
        self.link_points: list[tuple[int, int]] = []
        self.link_start = (0, 0)
        self.link_bend = 0.0

        self.saved_path: str | None = None
        self.saved_name = ""
        self.dirty = False
        self.status = ""
        self.status_color = TEXT_DIM
        self.status_timer = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def open_editor(self, graph: WeaveGraph | None = None,
                    path: str | None = None, name: str = "") -> None:
        if graph is not None and graph.canvas not in self.game.unlocked_canvases:
            graph = None
        self.graph = graph if graph is not None else WeaveGraph(canvas="small")
        self.active_element = "air"
        self.active_spell = None
        self.palette_mode = "runes"
        self.spell_scroll = 0
        self.selected_id = None
        self.hover_id = None
        self.hover_link = None
        self.drag_node = None
        self.link_src = None
        self.link_points = []
        self.saved_path = path
        self.saved_name = name
        self.dirty = False
        self.open = True
        self.time = 0.0
        if graph is not None:
            self.status = (f"Editing existing weave: {name or graph.name or 'untitled'}. "
                           "Move runes, bend arrows, then SAVE.")
        else:
            self.status = ("Place runes, then right-drag from one rune to another "
                           "to weave a mana relation.")
        self.status_color = TEXT_DIM
        self.status_timer = 5.0

    def close(self) -> None:
        if self.dirty and self.graph.nodes:
            spec = self.graph.resolve()
            if not spec.valid:
                self.status = "Fix the circuit before closing: " + spec.reason
                self.status_color = RED
                self.status_timer = 4.0
                self.game.audio.play("error", 0.5)
                return
            if not self.save():
                return
        self.open = False
        self.game.state = "playing"
        self.game.reload_spells()
        self.game.audio.play("ui", 0.3)
        self.game.toast("Weave canvas closed.", ACCENT, 1.8)

    def update(self, dt: float) -> None:
        self.time += dt
        if self.status_timer > 0:
            self.status_timer = max(0.0, self.status_timer - dt)
            if self.status_timer == 0.0 and not self.status.startswith("Saved"):
                self.status = ""

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def canvas_rect(self) -> pygame.Rect:
        data = CANVAS[self.graph.canvas]
        w, h = data["w"], data["h"]
        return pygame.Rect(CANVAS_AREA.centerx - w // 2,
                           CANVAS_AREA.y + (CANVAS_AREA.h - h) // 2, w, h)

    def node_screen(self, node: WeaveNode) -> tuple[float, float]:
        rect = self.canvas_rect()
        return rect.x + node.x * rect.w, rect.y + node.y * rect.h

    def _node_at(self, pos) -> WeaveNode | None:
        rect = self.canvas_rect()
        for node in reversed(self.graph.nodes):
            x, y = self.node_screen(node)
            if math.hypot(pos[0] - x, pos[1] - y) <= node_radius(node.size) + 5:
                return node
        return None

    def _curve_points(self, link: WeaveLink, samples: int = 26):
        a = self.graph.node(link.src)
        b = self.graph.node(link.dst)
        if a is None or b is None:
            return []
        ax, ay = self.node_screen(a)
        bx, by = self.node_screen(b)
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1:
            return []
        nx, ny = -dy / length, dx / length
        cx = (ax + bx) * 0.5 + nx * link.bend * length * 0.5
        cy = (ay + by) * 0.5 + ny * link.bend * length * 0.5
        pts = []
        for i in range(samples):
            t = i / (samples - 1)
            u = 1.0 - t
            pts.append((u * u * ax + 2 * u * t * cx + t * t * bx,
                        u * u * ay + 2 * u * t * cy + t * t * by))
        ra = node_radius(a.size)
        rb = node_radius(b.size)
        start = 0
        while start < len(pts) - 2 and math.hypot(pts[start][0] - ax, pts[start][1] - ay) < ra + 2:
            start += 1
        end = len(pts) - 1
        while end > start + 1 and math.hypot(pts[end][0] - bx, pts[end][1] - by) < rb + 3:
            end -= 1
        return pts[start:end + 1]

    def _link_at(self, pos) -> WeaveLink | None:
        best = None
        best_d = 7.0
        for link in self.graph.links:
            pts = self._curve_points(link, 22)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                mx, my = (x1 + x2) * 0.5, (y1 + y2) * 0.5
                d = math.hypot(pos[0] - mx, pos[1] - my)
                if d < best_d:
                    best_d = d
                    best = link
        return best

    def _bend_from_points(self, src: WeaveNode, end, points) -> float:
        ax, ay = self.node_screen(src)
        dx, dy = end[0] - ax, end[1] - ay
        length = math.hypot(dx, dy)
        if length < 8:
            return 0.0
        nx, ny = -dy / length, dx / length
        best = 0.0
        for px, py in points:
            off = ((px - ax) * nx + (py - ay) * ny) / (length * 0.5)
            if abs(off) > abs(best):
                best = off
        return _clamp(best, BEND_MIN, BEND_MAX)

    def spell_nodes_unlocked(self) -> bool:
        return self.game.level >= 3 and self.graph.canvas in ("medium", "large")

    def _woven_spells(self):
        result = []
        for spell in self.game.spells:
            if not spell.path.lower().endswith(".weave"):
                continue
            if self.saved_path and spell.path and \
                    os.path.abspath(spell.path) == os.path.abspath(self.saved_path):
                continue
            result.append(spell)
        return result

    def _find_woven(self, name: str):
        for spell in self.game.spells:
            if spell.name == name and spell.path.lower().endswith(".weave"):
                return spell
        return None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if not self.open:
            return
        if event.type == pygame.KEYDOWN:
            self._key_down(event)
            return
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            self._motion(event.pos)
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.mouse = event.pos
            if event.button == 1:
                self._left_down(event.pos)
            elif event.button == 3:
                self._right_down(event.pos)
            return
        if event.type == pygame.MOUSEBUTTONUP:
            self.mouse = event.pos
            if event.button == 1:
                self._left_up(event.pos)
            elif event.button == 3:
                self._right_up(event.pos)
            return
        if event.type == pygame.MOUSEWHEEL:
            self._wheel(event.y)
            return

    def _key_down(self, event: pygame.event.Event) -> None:
        key = event.key
        mods = pygame.key.get_mods()
        if key == pygame.K_ESCAPE:
            self.close()
            return
        if key == pygame.K_s and (mods & pygame.KMOD_CTRL):
            self.save()
            return
        if key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            if self.selected_id is not None:
                node = self.graph.node(self.selected_id)
                if node is not None:
                    self.graph.remove_node(node.id)
                    self.selected_id = None
                    self.dirty = True
                    self.status = "Rune erased."
                    self.status_color = TEXT_DIM
                    self.status_timer = 2.0
                    self.game.audio.play("error", 0.35)
            return
        if key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
            node = self.graph.node(self.selected_id) if self.selected_id is not None else None
            if node is not None:
                self._resize_node(node, -0.1)
            return
        if key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS):
            node = self.graph.node(self.selected_id) if self.selected_id is not None else None
            if node is not None:
                self._resize_node(node, 0.1)
            return
        if pygame.K_1 <= key <= pygame.K_4:
            self.active_element = ELEMENTS4[key - pygame.K_1]
            self.status = f"Drawing {self.active_element.upper()} runes."
            self.status_color = ELEMENTS[self.active_element]["color"]
            self.status_timer = 2.0
            self.game.audio.play("ui", 0.25)

    def _left_down(self, pos) -> None:
        if SAVE_RECT.collidepoint(pos):
            self.save()
            return
        if CLEAR_RECT.collidepoint(pos):
            if self.graph.nodes or self.graph.links:
                self.graph.nodes = []
                self.graph.links = []
                self.graph.next_id = 1
                self.selected_id = None
                self.saved_path = None
                self.saved_name = ""
                self.dirty = True
            self.status = "Canvas cleared."
            self.status_color = TEXT_DIM
            self.status_timer = 2.0
            self.game.audio.play("ui", 0.3)
            return
        if CLOSE_RECT.collidepoint(pos):
            self.close()
            return
        if DEMO_RECT.collidepoint(pos):
            if "medium" not in self.game.unlocked_canvases:
                self.status = "The Tornado demo needs the MEDIUM canvas. Finish quest 3."
                self.status_color = RED
                self.status_timer = 4.0
                self.game.audio.play("error", 0.45)
                return
            self.graph = tornado_graph()
            self.selected_id = None
            self.active_element = None
            self.active_spell = None
            self.palette_mode = "runes"
            self.saved_path = None
            self.saved_name = ""
            self.dirty = True
            self.status = ("Example loaded: four Air runes circulate clockwise. "
                           "Watch the arrows, then SAVE and cast it.")
            self.status_color = ELEMENTS["air"]["color"]
            self.status_timer = 7.0
            self.game.audio.play("ui", 0.4)
            return
        for key, rect in TIER_RECTS.items():
            if rect.collidepoint(pos):
                self._set_canvas(key)
                return
        if TAB_RUNES.collidepoint(pos):
            self.palette_mode = "runes"
            self.active_spell = None
            self.game.audio.play("ui", 0.2)
            return
        if TAB_SPELLS.collidepoint(pos):
            self.palette_mode = "spells"
            self.active_element = None
            self.game.audio.play("ui", 0.2)
            return
        if self.palette_mode == "runes":
            for i, element in enumerate(ELEMENTS4):
                chip = pygame.Rect(40, RUNE_Y + i * RUNE_STEP, 162, RUNE_H)
                if chip.collidepoint(pos):
                    self.active_element = element
                    self.active_spell = None
                    self.status = f"Drawing {element.upper()} runes."
                    self.status_color = ELEMENTS[element]["color"]
                    self.status_timer = 2.0
                    self.game.audio.play("ui", 0.25)
                    return
        elif self.spell_nodes_unlocked():
            spells = self._woven_spells()
            for i, spell in enumerate(spells[self.spell_scroll:self.spell_scroll + 8]):
                chip = pygame.Rect(40, SPELL_Y + i * SPELL_STEP, 162, SPELL_H)
                if chip.collidepoint(pos):
                    self.active_spell = spell.name
                    self.active_element = None
                    self.status = f"Placing spell node: {spell.name}."
                    self.status_color = ELEMENTS[spell.element]["color"]
                    self.status_timer = 2.5
                    self.game.audio.play("ui", 0.25)
                    return
        if not self.canvas_rect().collidepoint(pos):
            return
        node = self._node_at(pos)
        if node is not None:
            self.selected_id = node.id
            self.drag_node = node.id
            self.drag_origin = (node.x, node.y)
            sx, sy = self.node_screen(node)
            self.drag_offset = (sx - pos[0], sy - pos[1])
            return
        self._place_node(pos)

    def _left_up(self, pos) -> None:
        if self.drag_node is None:
            return
        node = self.graph.node(self.drag_node)
        self.drag_node = None
        if node is None:
            return
        if self.graph.over_budget() > 0.001:
            node.x, node.y = self.drag_origin
            self.status = "That move stretched the arrows past the mana budget."
            self.status_color = RED
            self.status_timer = 3.0
            self.game.audio.play("error", 0.5)
        else:
            self.dirty = True

    def _right_down(self, pos) -> None:
        link = self._link_at(pos)
        if link is not None:
            self.graph.remove_link(link)
            self.dirty = True
            self.status = "Relation erased."
            self.status_color = TEXT_DIM
            self.status_timer = 2.0
            self.game.audio.play("ui", 0.3)
            return
        node = self._node_at(pos)
        if node is not None:
            self.selected_id = node.id
            self.link_src = node.id
            self.link_start = pos
            self.link_points = [pos]
            self.link_bend = 0.0
            return
        if self.canvas_rect().collidepoint(pos):
            self.active_element = None
            self.active_spell = None
            self.selected_id = None

    def _right_up(self, pos) -> None:
        if self.link_src is None:
            return
        src = self.graph.node(self.link_src)
        moved = math.hypot(pos[0] - self.link_start[0], pos[1] - self.link_start[1]) > 6
        target = self._node_at(pos)
        if moved and src is not None and target is not None and target.id != src.id:
            old = next((l for l in self.graph.links
                        if l.src == src.id and l.dst == target.id), None)
            old_bend = old.bend if old is not None else None
            bend = self._bend_from_points(src, pos, self.link_points)
            link = self.graph.add_link(src.id, target.id, bend)
            if link is not None:
                link.bend = bend
                if self.graph.over_budget() > 0.001:
                    if old_bend is None:
                        self.graph.remove_link(link)
                    else:
                        link.bend = old_bend
                    self.status = "That arrow does not fit in the mana budget."
                    self.status_color = RED
                    self.status_timer = 3.0
                    self.game.audio.play("error", 0.5)
                else:
                    self.dirty = True
                    arrow = "clockwise" if bend < 0 else ("counter-clockwise" if bend > 0 else "straight")
                    self.status = (f"{src.element.capitalize()} -> "
                                   f"{target.element.capitalize()} ({arrow}).")
                    self.status_color = ELEMENTS[target.element]["color"]
                    self.status_timer = 3.0
                    self.game.audio.play("ui", 0.35)
        self.link_src = None
        self.link_points = []

    def _motion(self, pos) -> None:
        if self.drag_node is not None:
            node = self.graph.node(self.drag_node)
            if node is not None:
                rect = self.canvas_rect()
                x = (pos[0] + self.drag_offset[0] - rect.x) / max(1, rect.w)
                y = (pos[1] + self.drag_offset[1] - rect.y) / max(1, rect.h)
                node.x = _clamp(x, 0.04, 0.96)
                node.y = _clamp(y, 0.04, 0.96)
            return
        if self.link_src is not None:
            self.link_points.append(pos)
            src = self.graph.node(self.link_src)
            if src is not None:
                self.link_bend = self._bend_from_points(src, pos, self.link_points)
        self.hover_id = None
        self.hover_link = None
        node = self._node_at(pos)
        if node is not None:
            self.hover_id = node.id
        elif self.canvas_rect().collidepoint(pos):
            self.hover_link = self._link_at(pos)

    def _wheel(self, dy: int) -> None:
        self.mouse = pygame.mouse.get_pos()
        if self.palette_mode == "spells" and PALETTE.collidepoint(self.mouse):
            spells = self._woven_spells()
            self.spell_scroll = int(_clamp(self.spell_scroll + (-1 if dy > 0 else 1),
                                           0, max(0, len(spells) - 8)))
            return
        node = self._node_at(self.mouse)
        if node is None:
            return
        self._resize_node(node, 0.1 if dy > 0 else -0.1)

    def _resize_node(self, node: WeaveNode, delta: float) -> None:
        old = node.size
        node.size = _clamp(node.size + delta, NODE_MIN, NODE_MAX)
        if self.graph.over_budget() > 0.001:
            node.size = old
            self.status = "A larger rune would exceed the mana budget."
            self.status_color = RED
            self.status_timer = 2.5
            self.game.audio.play("error", 0.4)
            return
        self.dirty = True
        self.status = (f"{node.element.capitalize()} rune size {node.size:.1f} "
                       f"({node.cost():.1f} mana).")
        self.status_color = ELEMENTS[node.element]["color"]
        self.status_timer = 2.0
        self.game.audio.play("ui", 0.2)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _set_canvas(self, key: str) -> None:
        data = CANVAS[key]
        if key not in self.game.unlocked_canvases:
            self.status = (f"{data['label']} is locked. Complete quests to unlock "
                           "a larger canvas.")
            self.status_color = RED
            self.status_timer = 3.5
            self.game.audio.play("error", 0.45)
            return
        if key == "small" and self.graph.has_spell_nodes():
            self.status = "Spell nodes need a MEDIUM or HIGH canvas."
            self.status_color = RED
            self.status_timer = 3.0
            self.game.audio.play("error", 0.4)
            return
        if len(self.graph.nodes) > data["max_nodes"]:
            self.status = (f"{data['label']} canvas holds at most "
                           f"{data['max_nodes']} runes.")
            self.status_color = RED
            self.status_timer = 3.0
            self.game.audio.play("error", 0.4)
            return
        self.graph.canvas = key
        self.dirty = True
        self.status = f"{data['label']} canvas: {data['budget']:g} mana available."
        self.status_color = ACCENT
        self.status_timer = 2.5
        self.game.audio.play("ui", 0.3)

    def _place_node(self, pos) -> None:
        if self.active_spell is not None and not self.spell_nodes_unlocked():
            self.status = "Spell nodes unlock at level 3 on a MEDIUM or HIGH canvas."
            self.status_color = RED
            self.status_timer = 3.0
            return
        if self.active_element is None and self.active_spell is None:
            return
        rect = self.canvas_rect()
        x = (pos[0] - rect.x) / max(1, rect.w)
        y = (pos[1] - rect.y) / max(1, rect.h)
        spell = self._find_woven(self.active_spell) if self.active_spell else None
        if self.active_spell and spell is None:
            self.status = "That woven spell is no longer available."
            self.status_color = RED
            self.status_timer = 3.0
            return
        if spell is not None:
            node = self.graph.add_spell_node(spell, x, y, 1.0)
        else:
            node = self.graph.add_node(self.active_element, x, y, 1.0)
        if node is None:
            data = CANVAS[self.graph.canvas]
            self.status = f"This canvas holds at most {data['max_nodes']} runes."
            self.status_color = RED
            self.status_timer = 2.5
            self.game.audio.play("error", 0.4)
            return
        if self.graph.over_budget() > 0.001:
            self.graph.remove_node(node.id)
            self.status = "Not enough mana for another rune on this canvas."
            self.status_color = RED
            self.status_timer = 3.0
            self.game.audio.play("error", 0.5)
            return
        self.selected_id = node.id
        self.dirty = True
        if node.spell:
            self.status = (f"{node.spell} node placed "
                           f"({node.cost():.1f} mana, nested cast).")
            self.status_color = ELEMENTS[node.element]["color"]
        else:
            self.status = (f"{node.element.capitalize()} rune placed "
                           f"({node.cost():.1f} mana).")
            self.status_color = ELEMENTS[node.element]["color"]
        self.status_timer = 2.5
        self.game.audio.play("ui", 0.25)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _unique_name(self, base: str) -> str:
        used = set()
        for spell in self.game.spellbook.spells.values():
            if self.saved_path and spell.path and \
                    os.path.abspath(spell.path) == os.path.abspath(self.saved_path):
                continue
            used.add(spell.name.lower())
        name = base
        n = 2
        while name.lower() in used:
            name = f"{base} {n}"
            n += 1
        return name

    def save(self) -> bool:
        spec = self.graph.resolve()
        if not spec.valid:
            self.status = "Cannot save: " + spec.reason
            self.status_color = RED
            self.status_timer = 3.5
            self.game.audio.play("error", 0.5)
            return False
        if self.saved_path:
            name = self.saved_name
            path = self.saved_path
        else:
            name = self._unique_name(spec.name)
            slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "weave"
            path = os.path.join(self.game.spells_dir, slug + ".weave")
            n = 2
            while os.path.exists(path):
                path = os.path.join(self.game.spells_dir, f"{slug}_{n}.weave")
                n += 1
        try:
            save_weave(path, self.graph, name)
        except OSError as exc:
            self.status = f"Cannot save: {exc}"
            self.status_color = RED
            self.status_timer = 4.0
            self.game.audio.play("error", 0.5)
            return False
        self.saved_path = path
        self.saved_name = name
        self.dirty = False
        self.game.reload_spells()
        for i, spell in enumerate(self.game.spells):
            if spell.name == name:
                self.game.selected_index = i
                break
        self.game.stats["spells_saved"] += 1
        self.game.stats["weaves_saved"] += 1
        if spec.cycle_len >= 3:
            self.game.stats["weave_cycles"] += 1
        if spec.cost >= 500:
            self.game.stats["big_weaves"] += 1
        self.game._save_progress()
        self.status = (f"Saved '{name}' (cast {spec.mana} / raw {spec.cost:.0f} mana, "
                       "20% woven). It is now in your spellbook - close and cast it.")
        self.status_color = GREEN
        self.status_timer = 5.0
        self.game.toast(f"Weave saved: {name}", GREEN, 3.0)
        self.game.audio.play("heal", 0.55)
        self.game._update_quests()
        return True

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------
    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(BG)
        self._draw_header(surf)
        self._draw_palette(surf)
        self._draw_canvas(surf)
        self._draw_info(surf)
        self._draw_status(surf)

    def _draw_header(self, surf: pygame.Surface) -> None:
        draw_text(surf, "WEAVE CANVAS", (28, 24), 23, TEXT, bold=True)
        draw_text(surf, "Drag runes. Weave mana. Give the spell a shape.",
                  (28, 52), 10, TEXT_FAINT)
        for key, rect in TIER_RECTS.items():
            data = CANVAS[key]
            active = self.graph.canvas == key
            unlocked = key in self.game.unlocked_canvases
            if not unlocked:
                fill, border, ink = BG_PANEL, BORDER, TEXT_FAINT
            else:
                fill = ACCENT if active else (34, 30, 52) if rect.collidepoint(self.mouse) \
                    else BG_PANEL_LIGHT
                border = ACCENT if active else BORDER
                ink = TEXT if active else TEXT_DIM
            pygame.draw.rect(surf, fill, rect, border_radius=6)
            pygame.draw.rect(surf, border, rect, 1, border_radius=6)
            draw_text(surf, f"{data['label']}  {data['budget']:g}", (rect.centerx, rect.y + 8),
                      10, ink, bold=active, align="center")
            if not unlocked:
                pygame.draw.rect(surf, TEXT_FAINT, (rect.right - 15, rect.y + 11, 6, 5), 1)
                pygame.draw.circle(surf, TEXT_FAINT, (rect.right - 12, rect.y + 10), 3, 1)
        demo_unlocked = "medium" in self.game.unlocked_canvases
        active = DEMO_RECT.collidepoint(self.mouse)
        pygame.draw.rect(surf, (44, 36, 68) if active and demo_unlocked else BG_PANEL_LIGHT,
                         DEMO_RECT, border_radius=6)
        pygame.draw.rect(surf, ACCENT if active and demo_unlocked else BORDER, DEMO_RECT,
                         1, border_radius=6)
        draw_text(surf, "TORNADO DEMO", (DEMO_RECT.centerx, DEMO_RECT.y + 8), 9,
                  GOLD if demo_unlocked else TEXT_FAINT, bold=True, align="center")
        for rect, label, hot in (
            (SAVE_RECT, "SAVE", GREEN), (CLEAR_RECT, "CLEAR", TEXT_DIM),
            (CLOSE_RECT, "CLOSE", TEXT_DIM),
        ):
            hover = rect.collidepoint(self.mouse)
            pygame.draw.rect(surf, (36, 32, 54) if hover else BG_PANEL_LIGHT, rect,
                             border_radius=6)
            pygame.draw.rect(surf, hot if hover else BORDER, rect, 1, border_radius=6)
            draw_text(surf, label, (rect.centerx, rect.y + 9), 10, hot if hover else TEXT,
                      bold=True, align="center")
        pygame.draw.line(surf, BORDER, (28, 76), (OUTER.right - 28, 76), 1)

    def _draw_palette(self, surf: pygame.Surface) -> None:
        panel(surf, PALETTE, BG_PANEL, BORDER)
        for rect, label, mode in ((TAB_RUNES, "RUNES", "runes"),
                                  (TAB_SPELLS, "SPELLS", "spells")):
            active = self.palette_mode == mode
            hover = rect.collidepoint(self.mouse)
            pygame.draw.rect(surf, (38, 32, 58) if active else
                             (31, 28, 45) if hover else BG_PANEL_LIGHT, rect,
                             border_radius=6)
            pygame.draw.rect(surf, ACCENT if active else BORDER, rect, 1, border_radius=6)
            draw_text(surf, label, (rect.centerx, rect.y + 5), 9,
                      TEXT if active else TEXT_DIM, bold=True, align="center")
        if self.palette_mode == "runes":
            self._draw_rune_palette(surf)
        else:
            self._draw_spell_palette(surf)

    def _draw_rune_palette(self, surf: pygame.Surface) -> None:
        for i, element in enumerate(ELEMENTS4):
            rect = pygame.Rect(40, RUNE_Y + i * RUNE_STEP, 162, RUNE_H)
            active = self.active_element == element
            hover = rect.collidepoint(self.mouse)
            pygame.draw.rect(surf, (38, 32, 58) if active else
                             (31, 28, 45) if hover else BG_PANEL_LIGHT, rect, border_radius=7)
            pygame.draw.rect(surf, ACCENT if active else BORDER, rect, 1, border_radius=7)
            self._orb(surf, rect.x + 26, rect.centery, 13, element)
            draw_text(surf, element.capitalize(), (rect.x + 46, rect.y + 8), 12,
                      TEXT, bold=True)
            draw_text(surf, f"base {BASE_COST[element]:g}",
                      (rect.x + 46, rect.y + 26), 8, TEXT_FAINT)
            if active:
                draw_text(surf, "PLACING", (rect.right - 8, rect.y + 26), 8, ACCENT,
                          align="right")

        y = PALETTE.y + 282
        draw_text(surf, "PATTERNS", (PALETTE.x + 12, y), 10, TEXT_DIM, bold=True)
        y += 19
        patterns = [
            "Air ring -> Tornado (M)",
            "Water ring -> Maelstrom (M)",
            "Fire ring -> Firestorm (M)",
            "Earth ring -> Quake (M)",
            "Fire + Water loop -> Steam (M)",
            "Line of Earth -> Stone Wall",
            "Cluster -> Burst",
        ]
        for line in patterns:
            draw_text(surf, line, (PALETTE.x + 12, y), 9, TEXT_FAINT)
            y += 14
        y += 10
        draw_text(surf, "DRAWING", (PALETTE.x + 12, y), 10, TEXT_DIM, bold=True)
        y += 19
        hints = [
            "Click rune, click canvas.",
            "Left-drag rune to move.",
            "Right-drag rune -> rune.",
            "Curve the drag to bend.",
            "Wheel or [ ] = size.",
            "Right-click arrow = erase.",
            "Del = erase selected.",
        ]
        for line in hints:
            for part in wrap(line, PALETTE.w - 24, 9):
                draw_text(surf, part, (PALETTE.x + 12, y), 9, TEXT_FAINT)
                y += 12

    def _draw_spell_palette(self, surf: pygame.Surface) -> None:
        draw_text(surf, "WOVEN SPELL NODES", (PALETTE.x + 12, PALETTE.y + 36),
                  9, TEXT_DIM, bold=True)
        if not self.spell_nodes_unlocked():
            y = PALETTE.y + 58
            draw_text(surf, "LOCKED", (PALETTE.x + 12, y), 11, GOLD, bold=True)
            y += 20
            for line in ("Unlock at level 3.",
                         "Requires MEDIUM or HIGH canvas.",
                         f"Now: level {self.game.level}, {self.graph.canvas.upper()}."):
                for part in wrap(line, PALETTE.w - 24, 9):
                    draw_text(surf, part, (PALETTE.x + 12, y), 9, TEXT_FAINT)
                    y += 13
            return
        spells = self._woven_spells()
        self.spell_scroll = int(_clamp(self.spell_scroll, 0, max(0, len(spells) - 8)))
        if not spells:
            y = PALETTE.y + 60
            for line in ("No woven spells yet.",
                         "Save a weave and it becomes a node here."):
                draw_text(surf, line, (PALETTE.x + 12, y), 9, TEXT_FAINT)
                y += 14
            return
        for i, spell in enumerate(spells[self.spell_scroll:self.spell_scroll + 8]):
            rect = pygame.Rect(40, SPELL_Y + i * SPELL_STEP, 162, SPELL_H)
            active = self.active_spell == spell.name
            hover = rect.collidepoint(self.mouse)
            pygame.draw.rect(surf, (38, 32, 58) if active else
                             (31, 28, 45) if hover else BG_PANEL_LIGHT, rect,
                             border_radius=6)
            pygame.draw.rect(surf, ACCENT if active else BORDER, rect, 1, border_radius=6)
            self._orb(surf, rect.x + 20, rect.centery, 9, spell.element)
            draw_text(surf, spell.name, (rect.x + 36, rect.y + 4), 9, TEXT, bold=True)
            raw = spell.raw_mana or spell.mana
            draw_text(surf, f"node {raw:g} · cast {spell.mana}", (rect.x + 36, rect.y + 21),
                      8, TEXT_FAINT)
        if len(spells) > 8:
            end = min(len(spells), self.spell_scroll + 8)
            draw_text(surf, f"wheel to scroll  ({self.spell_scroll + 1}-{end}/{len(spells)})",
                      (PALETTE.x + 12, SPELL_Y + 8 * SPELL_STEP + 4), 8, TEXT_FAINT)
        y = PALETTE.y + 526
        for part in wrap("Spell nodes cast their woven spell as part of the new weave.",
                         PALETTE.w - 24, 9):
            draw_text(surf, part, (PALETTE.x + 12, y), 9, TEXT_FAINT)
            y += 12

    def _draw_canvas(self, surf: pygame.Surface) -> None:
        rect = self.canvas_rect()
        pygame.draw.rect(surf, (13, 15, 24), rect)
        for gx in range(rect.x + 20, rect.right, 36):
            pygame.draw.line(surf, (25, 28, 42), (gx, rect.y), (gx, rect.bottom), 1)
        for gy in range(rect.y + 20, rect.bottom, 36):
            pygame.draw.line(surf, (25, 28, 42), (rect.x, gy), (rect.right, gy), 1)
        pygame.draw.circle(surf, (29, 32, 48), (rect.centerx, rect.centery),
                           int(min(rect.w, rect.h) * 0.30), 1)
        pygame.draw.circle(surf, (25, 28, 42), (rect.centerx, rect.centery),
                           int(min(rect.w, rect.h) * 0.18), 1)
        pygame.draw.rect(surf, BORDER, rect, 2)
        data = CANVAS[self.graph.canvas]
        draw_text(surf, f"{data['label']} CANVAS  ·  {data['budget']:g} MANA",
                  (rect.x + 10, rect.y + 7), 8, TEXT_FAINT)

        if not self.graph.nodes:
            cx, cy = rect.centerx, rect.centery
            draw_text(surf, "Drag an element or spell node from the left onto the canvas.",
                      (cx, cy - 32), 12, TEXT_DIM, align="center")
            draw_text(surf, "Right-drag between two runes to weave a mana relation.",
                      (cx, cy - 12), 10, TEXT_FAINT, align="center")
            draw_text(surf, "Curve the drag to bend the arrow.",
                      (cx, cy + 8), 10, TEXT_FAINT, align="center")

        for link in self.graph.links:
            self._draw_link(surf, link)
        for node in self.graph.nodes:
            self._draw_node(surf, node)
        if self.link_src is not None:
            self._draw_link_preview(surf)

    def _draw_link(self, surf: pygame.Surface, link: WeaveLink) -> None:
        pts = self._curve_points(link)
        if len(pts) < 3:
            return
        a = self.graph.node(link.src)
        b = self.graph.node(link.dst)
        if a is None or b is None:
            return
        col = _mix(ELEMENTS[a.element]["color"], ELEMENTS[b.element]["color"])
        hover = self.hover_link is link
        pygame.draw.lines(surf, _dark(col, 0.55), False, pts, 5)
        pygame.draw.lines(surf, col, False, pts, 3 if hover else 2)
        self._arrow_head(surf, pts[-1], pts[-2], col, 8)
        if hover:
            mx, my = pts[len(pts) // 2]
            cost = link_cost(link, self.graph.by_id(), self.graph.canvas)
            draw_text(surf, f"{cost:.1f}", (mx, my - 14), 8, GOLD, align="center")

    def _draw_link_preview(self, surf: pygame.Surface) -> None:
        src = self.graph.node(self.link_src)
        if src is None:
            return
        ax, ay = self.node_screen(src)
        bx, by = self.mouse
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 3:
            return
        nx, ny = -dy / length, dx / length
        cx = (ax + bx) * 0.5 + nx * self.link_bend * length * 0.5
        cy = (ay + by) * 0.5 + ny * self.link_bend * length * 0.5
        pts = []
        for i in range(20):
            t = i / 19
            u = 1.0 - t
            pts.append((u * u * ax + 2 * u * t * cx + t * t * bx,
                        u * u * ay + 2 * u * t * cy + t * t * by))
        target = self._node_at(self.mouse)
        col = ELEMENTS[src.element]["color"]
        if target is not None and target.id != src.id:
            col = ELEMENTS[target.element]["color"]
        pygame.draw.lines(surf, _dark(col, 0.6), False, pts, 4)
        pygame.draw.lines(surf, col, False, pts, 2)
        self._arrow_head(surf, pts[-1], pts[-2], col, 7)

    def _arrow_head(self, surf, tip, prev, col, size: int) -> None:
        dx, dy = tip[0] - prev[0], tip[1] - prev[1]
        length = math.hypot(dx, dy)
        if length < 0.01:
            return
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        p1 = (tip[0] - ux * size + px * size * 0.55,
              tip[1] - uy * size + py * size * 0.55)
        p2 = (tip[0] - ux * size - px * size * 0.55,
              tip[1] - uy * size - py * size * 0.55)
        pygame.draw.polygon(surf, col, [tip, p1, p2])

    def _draw_node(self, surf: pygame.Surface, node: WeaveNode) -> None:
        x, y = self.node_screen(node)
        r = node_radius(node.size)
        data = ELEMENTS.get(node.element, ELEMENTS["arcane"])
        col = data["color"]
        selected = node.id == self.selected_id
        pygame.draw.circle(surf, (10, 11, 18), (int(x), int(y)), int(r + 3))
        pygame.draw.circle(surf, _dark(col, 0.45), (int(x), int(y)), int(r))
        pygame.draw.circle(surf, col, (int(x), int(y)), int(r), 2)
        pygame.draw.circle(surf, _dark(col, 0.75), (int(x), int(y)), int(r * 0.58), 1)
        if node.spell:
            pygame.draw.circle(surf, (255, 255, 255), (int(x), int(y)), int(r * 0.42), 1)
            label = node.spell[0].upper()
        else:
            label = node.element[0].upper()
        draw_text(surf, label, (x, y - 7), 11, TEXT, bold=True, align="center")
        draw_text(surf, f"{node.cost():.1f}", (x, y + r + 2), 8,
                  GOLD if selected else TEXT_FAINT, align="center")
        if selected:
            pygame.draw.circle(surf, (255, 255, 255), (int(x), int(y)), int(r + 5), 1)
            if self.drag_node == node.id:
                pygame.draw.circle(surf, ACCENT, (int(x), int(y)), int(r + 7), 1)
        elif node.id == self.hover_id:
            pygame.draw.circle(surf, ACCENT, (int(x), int(y)), int(r + 4), 1)

    def _orb(self, surf: pygame.Surface, x: int, y: int, r: int, element: str) -> None:
        data = ELEMENTS.get(element, ELEMENTS["arcane"])
        col = data["color"]
        pygame.draw.circle(surf, _dark(col, 0.55), (x, y), r)
        pygame.draw.circle(surf, col, (x, y), r, 2)
        pygame.draw.circle(surf, data["glow"], (x, y), max(2, r // 3))

    def _draw_info(self, surf: pygame.Surface) -> None:
        panel(surf, INFO, BG_PANEL, BORDER)
        x = INFO.x + 12
        y = INFO.y + 10
        draw_text(surf, "MANA BUDGET", (x, y), 10, TEXT_DIM, bold=True)
        y += 20
        graph = self.graph
        nodes_cost, links_cost = graph.cost_parts()
        spent = nodes_cost + links_cost
        budget = graph.budget()
        ratio = spent / max(0.001, budget)
        col = RED if ratio > 1.0 else GOLD if ratio > 0.78 else ACCENT
        bar(surf, pygame.Rect(x, y, INFO.w - 24, 10), min(spent, budget), budget, col,
            border=BORDER)
        y += 14
        draw_text(surf, f"{spent:.1f} / {budget:g} mana", (x, y), 11, TEXT)
        draw_text(surf, f"{max(0.0, budget - spent):.1f} left", (INFO.right - 12, y), 10,
                  col, align="right")
        y += 16
        draw_text(surf, f"runes {nodes_cost:.1f}  ·  arrows {links_cost:.1f}",
                  (x, y), 9, TEXT_FAINT)
        y += 24

        spec = graph.resolve()
        draw_text(surf, "RESULT", (x, y), 10, TEXT_DIM, bold=True)
        y += 18
        name = spec.name if spec.valid else "Unfinished weave"
        draw_text(surf, name, (x, y), 17, TEXT, bold=True)
        y += 24
        if spec.valid:
            shape = SHAPE_LABEL.get(spec.shape, spec.shape.upper())
            color = ELEMENTS.get(spec.element, ELEMENTS["arcane"])["color"]
            draw_text(surf, shape, (x, y), 9, color, bold=True)
            if spec.cycle_len:
                spin = spec.extra.get("spin", 1)
                draw_text(surf, "CW" if spin >= 0 else "CCW",
                          (x + 92, y), 9, TEXT_DIM, bold=True)
            draw_text(surf, f"{spec.mana} mana", (INFO.right - 12, y), 9, GOLD,
                      align="right")
            y += 16
            draw_text(surf, f"{spec.element} · power {spec.power:.2f}",
                      (x, y), 9, TEXT_DIM)
            y += 13
            draw_text(surf, f"radius {spec.radius:.1f}  ·  cd {spec.cooldown:.2f}s",
                      (x, y), 9, TEXT_DIM)
            y += 13
            spell_nodes = sum(1 for n in graph.nodes if n.spell)
            draw_text(surf, f"nodes {len(graph.nodes)}  ·  arrows {len(graph.links)}"
                      f"  ·  spell {spell_nodes}", (x, y), 9, TEXT_FAINT)
            y += 13
            draw_text(surf, f"cycle {spec.cycle_len}" if spec.cycle_len else "no closed loop",
                      (x, y), 9, TEXT_FAINT)
            y += 13
            draw_text(surf, f"raw {spec.cost:.1f}  ·  cast {spec.mana}  (-20%)",
                      (x, y), 9, GOLD)
            y += 17
            for part in wrap(spec.desc, INFO.w - 24, 9)[:8]:
                draw_text(surf, part, (x, y), 9, TEXT_DIM)
                y += 12
        else:
            draw_text(surf, "INVALID", (x, y), 9, RED, bold=True)
            y += 15
            for part in wrap(spec.reason or graph.validate() or "Unknown weave error.",
                             INFO.w - 24, 9)[:6]:
                draw_text(surf, part, (x, y), 9, RED)
                y += 12
            y += 6
            for part in wrap("A weave needs at least one rune and must stay inside "
                             "its mana budget.", INFO.w - 24, 9)[:4]:
                draw_text(surf, part, (x, y), 9, TEXT_FAINT)
                y += 12

        y = INFO.bottom - 62
        pygame.draw.line(surf, BORDER, (x, y - 8), (INFO.right - 12, y - 8), 1)
        draw_text(surf, "Every rune, spell node and arrow spends mana.", (x, y), 9, TEXT_FAINT)
        draw_text(surf, "Unused budget is not cast.", (x, y + 13), 9, TEXT_FAINT)
        draw_text(surf, "Ctrl+S saves a .weave spell.", (x, y + 26), 9, TEXT_FAINT)

    def _draw_status(self, surf: pygame.Surface) -> None:
        panel(surf, STATUS, BG_PANEL, BORDER)
        text = self.status
        color = self.status_color
        if not text:
            if self.graph.over_budget() > 0.001:
                text = f"Over budget by {self.graph.over_budget():.1f} mana."
                color = RED
            elif self.hover_id is not None and self.graph.node(self.hover_id) is not None \
                    and self.graph.node(self.hover_id).spell:
                node = self.graph.node(self.hover_id)
                raw = node.cost()
                text = (f"{node.spell} node · raw {raw:.1f} mana · "
                        f"echo cast {math.ceil(raw * 0.8)} mana")
                color = ELEMENTS.get(node.element, ELEMENTS["arcane"])["color"]
            else:
                text = ("LMB place/move  ·  RMB drag = relation  ·  RMB empty = stop  ·  "
                        "wheel / [ ] = size  ·  Del = erase  ·  Ctrl+S = save")
                color = TEXT_FAINT
        draw_text(surf, text, (STATUS.x + 12, STATUS.y + 11), 10, color)
