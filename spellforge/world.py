"""Tile based material simulation.

The world is a top-down grid of cells.  Solids are static, liquids flow and
gases rise.  A dirty-cell set keeps the cellular automaton cheap: only cells
that changed (or that neighbour a changed cell) are simulated.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable

from .config import ELEMENTS, GRID_H, GRID_W, TILE

# Material ids -------------------------------------------------------------
EMPTY, STONE, WOOD, PLANT, ICE, WATER, OIL, ACID, LAVA, FIRE, SMOKE, STEAM, ASH = range(13)


@dataclass(frozen=True)
class Mat:
    id: int
    name: str
    color: tuple[int, int, int]
    kind: str  # empty | solid | liquid | gas | decor
    density: float = 0.0
    flammable: float = 0.0
    solid: bool = False
    fuel: float = 0.0


MATS: list[Mat] = [
    Mat(EMPTY, "air", (19, 21, 32), "empty"),
    Mat(STONE, "stone", (94, 98, 112), "solid", density=99, solid=True),
    Mat(WOOD, "wood", (122, 84, 52), "solid", density=99, flammable=0.55, solid=True, fuel=2.2),
    Mat(PLANT, "plant", (58, 138, 74), "solid", density=99, flammable=0.75, solid=False, fuel=1.3),
    Mat(ICE, "ice", (140, 214, 238), "solid", density=99, solid=True),
    Mat(WATER, "water", (42, 104, 196), "liquid", density=3.0),
    Mat(OIL, "oil", (58, 48, 40), "liquid", density=1.7, flammable=1.0),
    Mat(ACID, "acid", (132, 212, 74), "liquid", density=2.4),
    Mat(LAVA, "lava", (236, 96, 30), "liquid", density=4.0),
    Mat(FIRE, "fire", (255, 146, 46), "gas", density=0.3),
    Mat(SMOKE, "smoke", (72, 72, 82), "gas", density=0.2),
    Mat(STEAM, "steam", (196, 208, 220), "gas", density=0.25),
    Mat(ASH, "ash", (58, 54, 50), "decor"),
]

COLORS = [m.color for m in MATS]
KIND = [m.kind for m in MATS]
DENSITY = [m.density for m in MATS]
FLAMMABLE = [m.flammable for m in MATS]
SOLID = [m.solid for m in MATS]
FUEL = [m.fuel for m in MATS]

NAME_TO_MAT = {m.name: m.id for m in MATS}

# Elements that spawn a material on impact.
ELEMENT_MATERIAL = {
    name: NAME_TO_MAT[data["material"]] if data["material"] else None
    for name, data in ELEMENTS.items()
}

DIRS4 = ((0, -1), (1, 0), (0, 1), (-1, 0))


class World:
    """A mutable tile grid with a tiny falling-sand style simulation."""

    def __init__(self, width: int = GRID_W, height: int = GRID_H, seed: int = 7):
        self.w = width
        self.h = height
        self.seed = seed
        self.rng = random.Random(seed)
        n = width * height
        self.mat = bytearray(n)
        self.life = [0.0] * n
        self.hp = [0.0] * n
        self.active: set[int] = set()
        self.stats: dict[str, int] = {
            "burned": 0,
            "evaporated": 0,
            "frozen": 0,
            "melted": 0,
            "dissolved": 0,
            "cooled": 0,
            "oil_ignited": 0,
        }
        self.time = 0.0

    # -- basics ------------------------------------------------------------
    def idx(self, x: int, y: int) -> int:
        return y * self.w + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.mat[y * self.w + x]
        return STONE

    def add_active(self, i: int) -> None:
        self.active.add(i)

    def touch(self, x: int, y: int) -> None:
        if not self.in_bounds(x, y):
            return
        i = y * self.w + x
        self.active.add(i)
        if x > 0:
            self.active.add(i - 1)
        if x < self.w - 1:
            self.active.add(i + 1)
        if y > 0:
            self.active.add(i - self.w)
        if y < self.h - 1:
            self.active.add(i + self.w)

    def set(self, x: int, y: int, material: int, life: float = 0.0) -> None:
        if not self.in_bounds(x, y):
            return
        i = y * self.w + x
        self.mat[i] = material
        self.life[i] = life
        self.hp[i] = 0.0
        self.touch(x, y)

    def set_idx(self, i: int, material: int, life: float = 0.0) -> None:
        self.mat[i] = material
        self.life[i] = life
        self.hp[i] = 0.0
        x = i % self.w
        y = i // self.w
        self.touch(x, y)

    # -- helpers used by spells -------------------------------------------
    def can_replace(self, x: int, y: int, new_mat: int) -> bool:
        m = self.get(x, y)
        if m == EMPTY:
            return True
        if KIND[m] == "gas":
            return True
        if new_mat in (STONE, ICE):
            return KIND[m] in ("liquid", "gas")
        return False

    def place(self, x: int, y: int, material: int, life: float = 0.0, force: bool = False) -> bool:
        if not self.in_bounds(x, y):
            return False
        m = self.get(x, y)
        if material == FIRE:
            if FLAMMABLE[m] > 0:
                self.ignite(x, y)
                return True
            if m not in (EMPTY, SMOKE, STEAM):
                return False
            self.set(x, y, FIRE, life if life else 0.7 + self.rng.random() * 0.5)
            return True
        if not force and not self.can_replace(x, y, material):
            return False
        if material == ICE and m == WATER:
            self.stats["frozen"] += 1
        self.set(x, y, material, life)
        return True

    def paint_circle(self, cx: float, cy: float, radius: float, material: int,
                     probability: float = 0.85, life: float = 0.0) -> int:
        """Paint a circular splat of material in tile coordinates."""
        r = max(0.6, radius)
        x0 = max(0, int(math.floor(cx - r)))
        x1 = min(self.w - 1, int(math.ceil(cx + r)))
        y0 = max(0, int(math.floor(cy - r)))
        y1 = min(self.h - 1, int(math.ceil(cy + r)))
        placed = 0
        r2 = r * r
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                dx = (x + 0.5) - cx
                dy = (y + 0.5) - cy
                if dx * dx + dy * dy > r2:
                    continue
                if self.rng.random() > probability:
                    continue
                if self.place(x, y, material, life):
                    placed += 1
        return placed

    def ignite(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        i = y * self.w + x
        m = self.mat[i]
        fuel = FLAMMABLE[m]
        if fuel <= 0:
            return False
        was_oil = m == OIL
        self.mat[i] = FIRE
        self.life[i] = 0.55 + fuel * 1.15
        self.hp[i] = 0.0
        self.touch(x, y)
        self.stats["burned"] += 1
        if was_oil:
            self.stats["oil_ignited"] += 1
        return True

    # -- queries -----------------------------------------------------------
    def solid_at(self, tx: int, ty: int) -> bool:
        return SOLID[self.get(tx, ty)]

    def solid_at_px(self, px: float, py: float) -> bool:
        return self.solid_at(int(px // TILE), int(py // TILE))

    def blocked_circle(self, px: float, py: float, radius: float) -> bool:
        x0 = int((px - radius) // TILE)
        x1 = int((px + radius) // TILE)
        y0 = int((py - radius) // TILE)
        y1 = int((py + radius) // TILE)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if not self.in_bounds(tx, ty) or not SOLID[self.mat[ty * self.w + tx]]:
                    continue
                rx = tx * TILE
                ry = ty * TILE
                cx = min(max(px, rx), rx + TILE)
                cy = min(max(py, ry), ry + TILE)
                if (cx - px) ** 2 + (cy - py) ** 2 < radius * radius:
                    return True
        return False

    def raycast_px(self, px: float, py: float, dx: float, dy: float,
                   max_dist: float, step: float = 2.0) -> tuple[float, float, bool]:
        """March through the grid. Returns (x, y, hit_solid)."""
        dist = 0.0
        while dist < max_dist:
            dist += step
            x = px + dx * dist
            y = py + dy * dist
            if self.solid_at_px(x, y):
                return x, y, True
        return px + dx * max_dist, py + dy * max_dist, False

    # -- simulation --------------------------------------------------------
    def step(self, dt: float = 1.0 / 60.0) -> None:
        self.time += dt
        if not self.active:
            return
        items = list(self.active)
        self.active.clear()
        budget = 3200
        if len(items) > budget:
            self.rng.shuffle(items)
            for i in items[budget:]:
                self.active.add(i)
            items = items[:budget]
        for i in items:
            if not (0 <= i < len(self.mat)):
                continue
            self._step_tile(i, dt)

    def _step_tile(self, i: int, dt: float) -> None:
        m = self.mat[i]
        if m == EMPTY or m == ASH:
            return
        x = i % self.w
        y = i // self.w
        if m == FIRE:
            self._step_fire(i, x, y, dt)
        elif m == LAVA:
            self._step_lava(i, x, y, dt)
        elif m == WATER:
            self._step_water(i, x, y, dt)
        elif m == ACID:
            self._step_acid(i, x, y, dt)
        elif m == STEAM:
            self._step_steam(i, x, y, dt)
        elif m == SMOKE:
            self._step_smoke(i, x, y, dt)
        elif KIND[m] in ("liquid", "gas"):
            self._move(i, x, y, m)

    def _step_fire(self, i: int, x: int, y: int, dt: float) -> None:
        self.life[i] -= dt
        rng = self.rng
        # Fire react to neighbours.
        for dx, dy in DIRS4:
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                continue
            j = ny * self.w + nx
            nm = self.mat[j]
            if nm == WATER:
                self.mat[j] = STEAM
                self.life[j] = 2.5
                self.mat[i] = SMOKE
                self.life[i] = 1.2
                self.stats["evaporated"] += 1
                self.touch(nx, ny)
                self.touch(x, y)
                return
            if nm == ICE:
                self.mat[j] = WATER
                self.hp[j] = 0.0
                self.stats["melted"] += 1
                self.touch(nx, ny)
            elif nm == LAVA:
                self.mat[i] = SMOKE
                self.life[i] = 0.9
                self.touch(x, y)
                return
            elif FLAMMABLE[nm] > 0:
                chance = FLAMMABLE[nm] * dt * (7.0 if nm == OIL else 3.0)
                if rng.random() < chance:
                    self.ignite(nx, ny)
        if self.mat[i] != FIRE:
            return
        if self.life[i] <= 0:
            self.mat[i] = ASH if rng.random() < 0.22 else EMPTY
            self.touch(x, y)
            return
        self._move(i, x, y, FIRE)

    def _step_lava(self, i: int, x: int, y: int, dt: float) -> None:
        for dx, dy in DIRS4:
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                continue
            j = ny * self.w + nx
            nm = self.mat[j]
            if nm == WATER:
                self.mat[j] = STEAM
                self.life[j] = 3.0
                self.mat[i] = STONE
                self.hp[i] = 0.0
                self.stats["cooled"] += 1
                self.touch(nx, ny)
                self.touch(x, y)
                return
            if FLAMMABLE[nm] > 0 and self.rng.random() < 0.5:
                self.ignite(nx, ny)
        # Molten rock is too viscous to flow: lava pools stay where they are.

    def _step_water(self, i: int, x: int, y: int, dt: float) -> None:
        for dx, dy in DIRS4:
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                continue
            m = self.get(nx, ny)
            if m == FIRE:
                self.set(nx, ny, SMOKE, 1.0)
                self.stats["evaporated"] += 1
            elif m == LAVA:
                self.set(x, y, STEAM, 2.5)
                self.set(nx, ny, STONE)
                self.stats["cooled"] += 1
                return
        self._move(i, x, y, WATER)

    def _step_acid(self, i: int, x: int, y: int, dt: float) -> None:
        rng = self.rng
        for dx, dy in DIRS4:
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                continue
            j = ny * self.w + nx
            nm = self.mat[j]
            if nm in (STONE, WOOD, ICE, PLANT) and rng.random() < 0.14:
                self.mat[j] = SMOKE
                self.life[j] = 0.8
                self.stats["dissolved"] += 1
                self.touch(nx, ny)
                if rng.random() < 0.35:
                    self.mat[i] = EMPTY
                    self.touch(x, y)
                    return
        self._move(i, x, y, ACID)

    def _step_steam(self, i: int, x: int, y: int, dt: float) -> None:
        self.life[i] -= dt
        if self.life[i] <= 0:
            if self.rng.random() < 0.55:
                self.mat[i] = WATER
            else:
                self.mat[i] = EMPTY
            self.touch(x, y)
            return
        self._move(i, x, y, STEAM)

    def _step_smoke(self, i: int, x: int, y: int, dt: float) -> None:
        self.life[i] -= dt
        if self.life[i] <= 0:
            self.mat[i] = EMPTY
            self.touch(x, y)
            return
        self._move(i, x, y, SMOKE)

    def _move(self, i: int, x: int, y: int, m: int) -> None:
        kind = KIND[m]
        rng = self.rng
        if kind == "gas":
            dirs = [(0, -1)]
            if rng.random() < 0.7:
                dirs.append((rng.choice((-1, 1)), -1))
            if rng.random() < 0.4:
                dirs.append((rng.choice((-1, 1)), 0))
        else:
            dirs = [(0, 1), (0, 1)]
            if rng.random() < 0.6:
                dirs.append((rng.choice((-1, 1)), 1))
            if rng.random() < 0.35:
                dirs.append((rng.choice((-1, 1)), 0))
            if rng.random() < 0.12:
                dirs.append((0, -1))
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                continue
            j = ny * self.w + nx
            tm = self.mat[j]
            if tm == EMPTY:
                self._swap(i, j)
                return
            tkind = KIND[tm]
            if kind == "liquid" and tkind == "liquid" and DENSITY[m] > DENSITY[tm] + 0.05:
                self._swap(i, j)
                return
            if kind == "liquid" and tkind == "gas":
                self._swap(i, j)
                return
            if kind == "gas" and tkind == "gas" and rng.random() < 0.2:
                self._swap(i, j)
                return

    def _swap(self, i: int, j: int) -> None:
        self.mat[i], self.mat[j] = self.mat[j], self.mat[i]
        self.life[i], self.life[j] = self.life[j], self.life[i]
        self.hp[i], self.hp[j] = self.hp[j], self.hp[i]
        x = i % self.w
        y = i // self.w
        self.touch(x, y)
        x2 = j % self.w
        y2 = j // self.w
        self.touch(x2, y2)

    # -- level generation --------------------------------------------------
    def build_arena(self) -> dict:
        """Build the starting arena. Returns spawn information (in pixels)."""
        rng = self.rng
        self.mat[:] = bytes(len(self.mat))
        self.active.clear()
        self.stats = {k: 0 for k in self.stats}

        def fill_rect(x0, y0, w, h, m, prob=1.0):
            for y in range(max(0, y0), min(self.h, y0 + h)):
                for x in range(max(0, x0), min(self.w, x0 + w)):
                    if rng.random() < prob:
                        self.set(x, y, m)

        def fill_ellipse(cx, cy, rx, ry, m, prob=1.0):
            for y in range(max(0, int(cy - ry)), min(self.h, int(cy + ry) + 1)):
                for x in range(max(0, int(cx - rx)), min(self.w, int(cx + rx) + 1)):
                    dx = (x - cx) / rx
                    dy = (y - cy) / ry
                    if dx * dx + dy * dy <= 1.0 and rng.random() < prob:
                        self.set(x, y, m)

        # Outer walls.
        fill_rect(0, 0, self.w, self.h, EMPTY)
        fill_rect(0, 0, self.w, 3, STONE)
        fill_rect(0, self.h - 3, self.w, 3, STONE)
        fill_rect(0, 0, 3, self.h, STONE)
        fill_rect(self.w - 3, 0, 3, self.h, STONE)
        # Organic cobble border.
        for y in range(3, self.h - 3):
            if rng.random() < 0.22:
                fill_rect(3, y, 1 + rng.randint(0, 2), 1, STONE)
                fill_rect(self.w - 4 - rng.randint(0, 2), y, 2, 1, STONE)

        # Great hall pillars.
        for px, py, pr in ((45, 30, 5), (135, 30, 5), (45, 70, 5), (135, 70, 5),
                           (90, 18, 6), (90, 82, 6)):
            fill_ellipse(px, py, pr, pr, STONE)
            fill_ellipse(px, py, pr - 1.6, pr - 1.6, EMPTY)

        # Water pond, bottom left.
        fill_ellipse(36, 66, 19, 12, WATER)
        for y in range(50, 83):
            for x in range(14, 60):
                dx = (x - 36) / 20.2
                dy = (y - 66) / 13.2
                if 0.92 < dx * dx + dy * dy <= 1.28 and rng.random() < 0.5:
                    self.set(x, y, STONE)

        # Oil mire, top right.
        fill_ellipse(146, 26, 12, 8, OIL, 0.95)

        # Ice shelf, bottom right.
        fill_ellipse(152, 76, 12, 8, ICE, 0.92)

        # Lava pool, top middle, ringed by stone.
        fill_ellipse(92, 24, 7, 4.5, LAVA, 0.95)
        for y in range(15, 33):
            for x in range(80, 104):
                dx = (x - 92) / 8.2
                dy = (y - 24) / 5.6
                if 0.85 < dx * dx + dy * dy <= 1.2 and rng.random() < 0.45:
                    self.set(x, y, STONE)

        # Groves of wood and plants.
        for gx, gy, gr in ((28, 28, 13), (120, 58, 15), (70, 76, 10), (156, 48, 8)):
            for _ in range(int(gr * 2.4)):
                x = int(rng.gauss(gx, gr * 0.55))
                y = int(rng.gauss(gy, gr * 0.55))
                if self.in_bounds(x, y) and self.get(x, y) in (EMPTY, PLANT):
                    if rng.random() < 0.45:
                        self.set(x, y, WOOD)
                    else:
                        self.set(x, y, PLANT)

        # A few sandbags... stone clusters for cover.
        for _ in range(26):
            x = rng.randint(20, self.w - 20)
            y = rng.randint(14, self.h - 14)
            if self.get(x, y) == EMPTY and 30 < x < self.w - 30:
                fill_ellipse(x, y, rng.randint(1, 3), rng.randint(1, 2), STONE, 0.7)

        # Clear a spawn plaza in the middle.
        fill_ellipse(90, 50, 9, 7, EMPTY)

        def px(tx, ty):
            return (tx + 0.5) * TILE, (ty + 0.5) * TILE

        spawns = {
            "player": px(90, 50),
            "dummies": [px(68, 44), px(112, 56), px(92, 72)],
            "stalkers": [px(158, 52), px(24, 48), px(90, 12), px(148, 88)],
            "eyes": [px(128, 34), px(52, 60)],
        }
        return spawns
