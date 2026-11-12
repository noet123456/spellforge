"""Executes compiled spells against the live game world."""

from __future__ import annotations

import math
import random

from pygame import Vector2

from .config import ELEMENTS, TILE
from .effects import Beam, Field, Projectile, Ring, Shield, Vortex
from .spell_lang import Instruction, SpellDef
from .world import (ELEMENT_MATERIAL, EMPTY, FIRE, ICE, KIND, LAVA, SMOKE, STEAM,
                    WATER, World)
from .entities import move_circle


def _clamp_point(p: Vector2, world: World) -> Vector2:
    return Vector2(
        max(TILE, min(world.w * TILE - TILE, p.x)),
        max(TILE, min(world.h * TILE - TILE, p.y)),
    )


class SpellRuntime:
    def __init__(self, game):
        self.game = game

    # ------------------------------------------------------------------
    # Program execution
    # ------------------------------------------------------------------
    def execute(self, program: list[Instruction], caster, origin: Vector2,
                aim: Vector2, aim_point: Vector2, depth: int = 0) -> None:
        if depth > 3:
            return
        if aim.length_squared() < 0.0001:
            aim = Vector2(1, 0)
        else:
            aim = aim.normalize()
        for ins in program:
            self._execute_instruction(ins, caster, origin, aim, aim_point, depth)

    def _execute_instruction(self, ins: Instruction, caster, origin: Vector2,
                             aim: Vector2, aim_point: Vector2, depth: int) -> None:
        name = ins.name
        p = ins.params
        world = self.game.world
        elem = ins.element or "arcane"

        if name == "_weave":
            # Graph-forged spells lower to this internal instruction.
            shape = ins.extra.get("shape", "burst")
            if shape in ("vortex", "steam"):
                center = _clamp_point(aim_point + aim * (p.get("offset", 0.0) * TILE), world)
                radius_px = p["radius"] * TILE
                spin = 1 if p.get("spin", 1.0) >= 0 else -1
                vortex = Vortex(center.x, center.y, radius_px, elem, p["power"],
                                 p["life"], p.get("pull", 1.0), spin)
                self.game.vortices.append(vortex)
                self.game.stats["vortex_casts"] += 1
                self.game.rings.append(Ring(center.x, center.y, 8, radius_px, 0.55,
                                            ELEMENTS[elem]["color"], 2))
                self.game.particles.burst(center.x, center.y, elem, 26, speed=130,
                                          life=0.65, size=2.6)
                self.game.shake(min(6.0, 2.0 + p["power"]))
                self.game.audio.play("boom" if elem in ("fire", "earth") else "cast", 0.5)
                caster.cast_flash = 0.2
            return

        if name == "bolt":
            start = _clamp_point(origin + aim * (p["offset"] * TILE), world)
            speed = p["speed"] * TILE
            radius = 2.0 + p["size"] * 1.1
            damage = p["power"] * 12.0 * ELEMENTS[elem]["damage"]
            proj = Projectile(
                start.x, start.y, aim.x * speed, aim.y * speed, radius, elem, damage,
                owner=caster, pierce=int(p["pierce"]), homing=p["homing"],
                life=p["life"], power=p["power"],
                on_hit=ins.events.get("hit"), on_expire=ins.events.get("expire"),
                size=p["size"],
            )
            self.game.projectiles.append(proj)
            self.game.particles.burst(start.x, start.y, elem, 4, speed=50, life=0.3)
            caster.cast_flash = 0.16

        elif name == "volley":
            count = int(p["count"])
            spread = math.radians(p["spread"])
            speed = p["speed"] * TILE
            damage = p["power"] * 11.0 * ELEMENTS[elem]["damage"]
            radius = 2.0 + p["size"] * 1.0
            start = _clamp_point(origin + aim * (p["offset"] * TILE), world)
            for i in range(count):
                t = 0.0 if count == 1 else i / (count - 1) - 0.5
                direction = aim.rotate_rad(t * spread)
                self.game.projectiles.append(Projectile(
                    start.x, start.y, direction.x * speed, direction.y * speed,
                    radius, elem, damage, owner=caster, pierce=0, homing=0.0,
                    life=1.9, power=p["power"], size=p["size"],
                ))
            self.game.particles.burst(start.x, start.y, elem, 5, speed=60, life=0.3)
            caster.cast_flash = 0.16

        elif name == "burst":
            center = _clamp_point(aim_point + aim * (p["offset"] * TILE), world)
            radius_tiles = p["radius"]
            self.impact(center, elem, p["power"], radius_tiles, caster)
            self.game.rings.append(Ring(center.x, center.y, 4, radius_tiles * TILE,
                                        0.35, ELEMENTS[elem]["color"], 2))
            self.game.shake(min(7.0, 2.0 + p["power"] * 2.0 + radius_tiles * 0.4))
            caster.cast_flash = 0.2

        elif name == "beam":
            origin2 = _clamp_point(origin + aim * (p["offset"] * TILE), world)
            self._fire_beam(origin2, aim, ins, caster, depth)
            caster.cast_flash = 0.2

        elif name == "wall":
            self._raise_wall(aim_point, aim, ins, p, elem, caster)
            caster.cast_flash = 0.2

        elif name == "orb":
            center = _clamp_point(aim_point + aim * (p["offset"] * TILE), world)
            radius_px = p["radius"] * TILE
            self.game.fields.append(Field(center.x, center.y, radius_px, elem,
                                          p["power"], p["life"], caster))
            # A small initial bloom makes the field readable.
            self.impact(center, elem, p["power"] * 0.5, p["radius"] * 0.68, caster, splat=True)
            self.game.rings.append(Ring(center.x, center.y, 5, radius_px, 0.5,
                                        ELEMENTS[elem]["color"], 2))
            caster.cast_flash = 0.2

        elif name == "shield":
            radius_px = p["radius"] * TILE
            self.game.shields.append(Shield(caster, radius_px, elem, p["power"], p["life"]))
            self.game.rings.append(Ring(caster.x, caster.y, 4, radius_px, 0.4,
                                        ELEMENTS[elem]["color"], 2))
            caster.cast_flash = 0.18

        elif name == "dash":
            caster.dash_v = aim * (p["power"] * 72.0)
            caster.dash_element = elem
            self.game.particles.burst(caster.x, caster.y, elem, 12, speed=100, life=0.5)
            self.game.shake(1.5)
            caster.cast_flash = 0.18

        elif name == "blink":
            distance = p["distance"] * TILE
            step = 3.0
            traveled = 0.0
            pos = Vector2(caster.x, caster.y)
            last_good = pos.copy()
            while traveled < distance:
                traveled += step
                candidate = pos + aim * min(step, distance - (traveled - step))
                if world.blocked_circle(candidate.x, candidate.y, caster.r):
                    break
                last_good = candidate
            self.game.particles.burst(caster.x, caster.y, "arcane", 12, speed=70, life=0.4)
            caster.x, caster.y = last_good.x, last_good.y
            self.game.particles.burst(caster.x, caster.y, "arcane", 12, speed=70, life=0.5)
            self.game.rings.append(Ring(caster.x, caster.y, 3, 30, 0.3,
                                        ELEMENTS["arcane"]["color"], 2))
            caster.cast_flash = 0.18

        elif name == "heal":
            amount = min(p["amount"], caster.max_hp - caster.hp)
            if amount > 0:
                caster.hp += amount
                self.game.add_floater(caster.x, caster.y - 18, f"+{int(amount)}", (120, 240, 150), 15)
                self.game.particles.burst(caster.x, caster.y, "light", 16, speed=55, life=0.8)
                self.game.rings.append(Ring(caster.x, caster.y, 4, 34, 0.45, (170, 255, 190), 2))
                self.game.audio.play("heal", 0.7)
            caster.cast_flash = 0.15

    # ------------------------------------------------------------------
    # Concrete effects
    # ------------------------------------------------------------------
    def _fire_beam(self, origin: Vector2, aim: Vector2, ins: Instruction,
                   caster, depth: int) -> None:
        p = ins.params
        world = self.game.world
        elem = ins.element or "arcane"
        length = p["length"] * TILE
        width_px = p["width"] * TILE
        damage = p["power"] * 14.0 * ELEMENTS[elem]["damage"]
        perp = Vector2(-aim.y, aim.x)

        end = origin + aim * length
        traveled = 0.0
        step = 3.0
        pos = origin.copy()
        hit_wall = False
        while traveled < length:
            traveled = min(length, traveled + step)
            pos = origin + aim * traveled
            if (not (0 <= pos.x < world.w * TILE and 0 <= pos.y < world.h * TILE)
                    or world.solid_at_px(pos.x, pos.y)):
                hit_wall = True
                break
        if not hit_wall:
            pos = origin + aim * length

        # Damage every enemy crossed by the ray (each target once).
        hit_ids: set[int] = set()
        for e in self.game.enemies:
            if not e.alive or id(e) in hit_ids:
                continue
            rel = Vector2(e.x, e.y) - origin
            along = rel.dot(aim)
            if along < 0 or along > traveled:
                continue
            if abs(rel.dot(perp)) > width_px * 0.5 + e.r:
                continue
            hit_ids.add(id(e))
            self._damage_one(e, damage, elem, caster, 1.0)
            self.game.particles.burst(e.x, e.y, elem, 5, speed=70, life=0.35)

        # Scorch the world along the beam.
        steps = max(1, int(traveled // (TILE * 0.9)))
        for i in range(steps + 1):
            pt = origin + aim * (traveled * i / steps)
            tx = int(pt.x // TILE)
            ty = int(pt.y // TILE)
            self._paint_small(tx, ty, elem, p["power"] * 0.35)

        self.game.beams.append(Beam(origin.x, origin.y, pos.x, pos.y,
                                    ELEMENTS[elem]["color"], 0.16, max(2, int(width_px))))
        for _ in range(int(traveled / 10)):
            t = random.random()
            pt = origin + aim * (traveled * t)
            self.game.particles.add_spark(pt.x, pt.y, ELEMENTS[elem]["color"])
        self.game.shake(min(5.0, 1.0 + p["power"] * 1.6))

        if "hit" in ins.events:
            self.execute(ins.events["hit"], caster, pos, aim, pos, depth + 1)
        self.impact(pos, elem, p["power"] * 0.7, max(0.7, p["width"]), caster, splat=True)

    def _raise_wall(self, aim_point: Vector2, aim: Vector2, ins: Instruction,
                    p: dict, elem: str, caster) -> None:
        world = self.game.world
        center = _clamp_point(aim_point + aim * (p["offset"] * TILE), world)
        perp = Vector2(-aim.y, aim.x)
        mat = ELEMENT_MATERIAL.get(elem)
        if mat is None:
            return
        length = int(p["length"])
        height = int(p["height"])
        life = p["life"]
        placed = 0
        for i in range(-(length // 2), length - length // 2):
            base = center + perp * (i * TILE)
            for h in range(height):
                offset = (h - (height - 1) * 0.5) * TILE
                pt = base + aim * offset
                tx = int(pt.x // TILE)
                ty = int(pt.y // TILE)
                if world.place(tx, ty, mat):
                    placed += 1
                    if mat not in (FIRE, WATER):
                        self.game.add_timed_tile(tx, ty, mat, life)
        color = ELEMENTS[elem]["color"]
        for _ in range(min(40, placed)):
            self.game.particles.burst(center.x + random.uniform(-length * 3, length * 3),
                                      center.y + random.uniform(-height * 4, height * 4),
                                      elem, 1, speed=35, life=0.4, size=2)
        self.game.rings.append(Ring(center.x, center.y, 4, length * TILE * 0.5, 0.35, color, 1))
        caster.cast_flash = 0.18

    def impact(self, center: Vector2, elem: str, power: float, radius_tiles: float,
               caster, splat: bool = True, damage_scale: float = 1.0) -> float:
        """Apply an elemental detonation. Returns total damage dealt."""
        world = self.game.world
        data = ELEMENTS[elem]
        radius_px = max(4.0, radius_tiles * TILE)
        total = 0.0

        if splat:
            mat = ELEMENT_MATERIAL.get(elem)
            if mat is not None:
                prob = 0.9
                r = radius_tiles
                if elem in ("fire", "water"):
                    r *= 0.8
                elif elem == "earth":
                    r *= 0.55
                    prob = 0.7
                elif elem == "poison":
                    r *= 0.7
                    prob = 0.75
                world.paint_circle(center.x / TILE, center.y / TILE, r, mat, prob)

        if elem == "water":
            self._douse(center, radius_px)
        elif elem == "air":
            self._push(center, radius_px, power)

        base = power * 13.0 * data["damage"] * damage_scale
        for e in list(self.game.enemies):
            if not e.alive:
                continue
            dx = e.x - center.x
            dy = e.y - center.y
            d = math.hypot(dx, dy)
            if d > radius_px + e.r:
                continue
            falloff = max(0.35, 1.0 - 0.55 * (d / max(1.0, radius_px)))
            total += self._damage_one(e, base * falloff, elem, caster, falloff)

        if elem == "lightning" and self._near_water(center, radius_px * 0.5):
            # Conducting through water widens the discharge.
            for e in list(self.game.enemies):
                if not e.alive:
                    continue
                if math.hypot(e.x - center.x, e.y - center.y) <= radius_px * 1.8 + e.r:
                    if e.wet > 0 or abs(e.x - center.x) < radius_px:
                        total += self._damage_one(e, base * 0.55, "lightning", caster, 0.7)

        self.game.particles.burst(center.x, center.y, elem,
                                  10 + int(power * 6), speed=70 + power * 40,
                                  life=0.4 + power * 0.12, size=2.0 + power * 0.5)
        return total

    def _damage_one(self, enemy, amount: float, elem: str, caster, falloff: float) -> float:
        if amount <= 0:
            return 0.0
        if elem == "lightning" and enemy.wet > 0:
            amount *= 1.5
        real = enemy.take_damage(amount, elem)
        game = self.game
        if real > 0:
            game.add_floater(enemy.x + random.uniform(-6, 6), enemy.y - enemy.r - 2,
                             str(int(round(real))), ELEMENTS[elem]["color"],
                             15 if real >= 12 else 13, 0.7)
            game.audio.play("hit", min(0.7, 0.15 + real * 0.012))
            game.cast_damage += real
            game.total_damage += real
            game.stats["best_cast_damage"] = max(game.stats.get("best_cast_damage", 0),
                                                 game.cast_damage)
            if game.cast_damage >= 80 and not game._overkill_this_cast:
                game._overkill_this_cast = True
                game.stats["overkills"] += 1
            if elem == "fire":
                enemy.burn = max(enemy.burn, 1.2 + amount * 0.03)
            elif elem == "ice":
                enemy.chill = max(enemy.chill, 1.6 + amount * 0.02)
            elif elem == "poison":
                enemy.poison = max(enemy.poison, 2.0 + amount * 0.04)
            elif elem == "water":
                enemy.wet = max(enemy.wet, 3.0)
                enemy.burn = 0.0
            elif elem == "lightning":
                enemy.shock = 0.35
            elif elem == "dark":
                heal = min(real * 0.35, caster.max_hp - caster.hp)
                if heal > 0:
                    caster.hp += heal
                    game.particles.burst(caster.x, caster.y, "dark", 4, speed=40, life=0.4)
        if not enemy.alive:
            game.on_enemy_killed(enemy)
        return real

    def _douse(self, center: Vector2, radius_px: float) -> None:
        world = self.game.world
        r = int(radius_px // TILE) + 1
        cx = int(center.x // TILE)
        cy = int(center.y // TILE)
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
                    continue
                m = world.get(x, y)
                if m == FIRE:
                    world.set(x, y, SMOKE, 1.0)
                elif m == LAVA:
                    world.set(x, y, SMOKE, 1.2)
                    world.stats["cooled"] += 1

    def _push(self, center: Vector2, radius_px: float, power: float) -> None:
        world = self.game.world
        for e in self.game.enemies:
            if not e.alive:
                continue
            delta = Vector2(e.x, e.y) - center
            d = delta.length()
            if d < 0.001 or d > radius_px + e.r:
                continue
            push = (1.0 - d / (radius_px + e.r)) * power * 26.0
            e.x, e.y = move_circle(world, e.x, e.y, e.r, delta.x / d * push, delta.y / d * push)

    def _near_water(self, center: Vector2, radius_px: float) -> bool:
        world = self.game.world
        r = int(radius_px // TILE) + 1
        cx = int(center.x // TILE)
        cy = int(center.y // TILE)
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if world.get(x, y) == WATER:
                    return True
        return False

    def _paint_small(self, tx: int, ty: int, elem: str, amount: float) -> None:
        mat = ELEMENT_MATERIAL.get(elem)
        if mat is None:
            return
        if random.random() < amount:
            self.game.world.place(tx, ty, mat)
