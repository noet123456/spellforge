"""Actors: the wizard, enemies and their status effects."""

from __future__ import annotations

import math
import random

from pygame import Vector2

from .config import ELEMENTS, TILE
from .world import ACID, EMPTY, FIRE, ICE, LAVA, WATER, World

PLAYER_RADIUS = 8.0
PLAYER_SPEED = 140.0


def move_circle(world: World, x: float, y: float, r: float,
                dx: float, dy: float) -> tuple[float, float]:
    nx = x + dx
    if not world.blocked_circle(nx, y, r):
        x = nx
    ny = y + dy
    if not world.blocked_circle(x, ny, r):
        y = ny
    x = max(r, min(world.w * TILE - r, x))
    y = max(r, min(world.h * TILE - r, y))
    return x, y


class Entity:
    kind = "entity"

    def __init__(self, x: float, y: float, radius: float, hp: float):
        self.x = x
        self.y = y
        self.r = radius
        self.hp = hp
        self.max_hp = hp
        self.alive = True
        self.vx = 0.0
        self.vy = 0.0
        self.hit_flash = 0.0
        self.burn = 0.0
        self.poison = 0.0
        self.chill = 0.0
        self.wet = 0.0
        self.shock = 0.0
        self.dot_timer = 0.0
        self.last_hit_by: str | None = None

    @property
    def pos(self) -> Vector2:
        return Vector2(self.x, self.y)

    def take_damage(self, amount: float, element: str | None = None) -> float:
        if not self.alive or amount <= 0:
            return 0.0
        real = min(self.hp, amount)
        self.hp -= amount
        self.hit_flash = 0.16
        self.last_hit_by = element
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
        return real

    def status_tick(self, dt: float, world: World, game) -> float:
        """Apply damage over time and environment effects. Returns dot damage."""
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.chill = max(0.0, self.chill - dt)
        self.wet = max(0.0, self.wet - dt)
        self.shock = max(0.0, self.shock - dt)

        # Environment contact.
        tx = int(self.x // TILE)
        ty = int(self.y // TILE)
        ground = world.get(tx, ty)
        dot_hazard = 0.0
        if ground == FIRE:
            self.burn = max(self.burn, 1.2)
        elif ground == WATER:
            self.wet = max(self.wet, 2.0)
            self.burn = 0.0
        elif ground == ICE:
            self.chill = max(self.chill, 1.0)
        elif ground == ACID:
            self.poison = max(self.poison, 2.5)
            dot_hazard = 7.0 * dt
        elif ground == LAVA:
            self.burn = max(self.burn, 3.0)
            dot_hazard = 26.0 * dt
        else:
            dot_hazard = 0.0

        dot = dot_hazard
        if self.burn > 0:
            self.burn -= dt
            dot += 5.5 * dt
            if random.random() < dt * 8:
                game.particles.burst(self.x, self.y, "fire", 1, speed=20)
        if self.poison > 0:
            self.poison -= dt
            dot += 4.0 * dt
            if random.random() < dt * 5:
                game.particles.burst(self.x, self.y, "poison", 1, speed=16)
        if dot > 0:
            self.take_damage(dot)
        return dot


class Player(Entity):
    kind = "player"

    def __init__(self, x: float, y: float):
        super().__init__(x, y, PLAYER_RADIUS, 100)
        self.mana = 1000.0
        self.max_mana = 1000.0
        self.mana_regen = 30.0
        self.aim = Vector2(1, 0)
        self.invuln = 0.0
        self.dash_v = Vector2()
        self.dash_element = "arcane"
        self.cooldowns: dict[str, float] = {}
        self.cast_flash = 0.0
        self.walk_phase = 0.0
        self.step_timer = 0.0
        self.kills = 0

    def update(self, dt: float, game) -> None:
        self.invuln = max(0.0, self.invuln - dt)
        self.cast_flash = max(0.0, self.cast_flash - dt)
        self.mana = min(self.max_mana, self.mana + self.mana_regen * dt)
        for name in list(self.cooldowns):
            self.cooldowns[name] = max(0.0, self.cooldowns[name] - dt)
            if self.cooldowns[name] == 0.0:
                del self.cooldowns[name]

        keys = game.keys
        mx = (1 if (keys["d"] or keys["right"]) else 0) - (1 if (keys["a"] or keys["left"]) else 0)
        my = (1 if (keys["s"] or keys["down"]) else 0) - (1 if (keys["w"] or keys["up"]) else 0)
        direction = Vector2(mx, my)
        if direction.length_squared() > 0:
            direction = direction.normalize()
            self.walk_phase += dt * 9
        speed = PLAYER_SPEED
        if self.chill > 0:
            speed *= 0.55
        move = direction * speed * dt + self.dash_v * dt
        self.x, self.y = move_circle(game.world, self.x, self.y, self.r, move.x, move.y)
        self.dash_v *= max(0.0, 1.0 - dt * 7.0)
        if self.dash_v.length_squared() < 4:
            self.dash_v.update(0, 0)

        if self.wet > 0:
            self.mana_regen = max(8.0, self.max_mana * 0.020)
        else:
            self.mana_regen = max(10.0, self.max_mana * 0.030)

        # Footstep dust.
        if direction.length_squared() > 0 and self.dash_v.length_squared() < 400:
            self.step_timer -= dt
            if self.step_timer <= 0:
                self.step_timer = 0.28
                game.particles.dust(self.x, self.y + self.r * 0.6)


class Enemy(Entity):
    kind = "enemy"

    def __init__(self, x: float, y: float, radius: float, hp: float, speed: float,
                 name: str, color: tuple[int, int, int]):
        super().__init__(x, y, radius, hp)
        self.speed = speed
        self.name = name
        self.color = color
        self.spawn = (x, y)
        self.respawn_at = 0.0
        self.attack_cd = 0.0
        self.anim = random.random() * 10
        self.contact_damage = 9.0
        self.ranged = False

    def update(self, dt: float, game) -> None:
        if not self.alive:
            return
        self.anim += dt
        self.attack_cd = max(0.0, self.attack_cd - dt)
        player = game.player
        to_player = player.pos - self.pos
        dist = max(0.001, to_player.length())
        direction = to_player / dist

        speed = self.speed * (0.5 if self.chill > 0 else 1.0)
        if self.ranged:
            desired = 150.0
            if dist < desired - 20:
                direction = -direction
            elif dist < desired + 20:
                direction = Vector2(-direction.y, direction.x) * 0.6
            if self.attack_cd <= 0 and dist < 340:
                self.attack_cd = 2.1
                game.spawn_hostile_bolt(self.x, self.y, direction, speed=180, damage=9,
                                        element="dark")
        else:
            if dist < player.r + self.r + 4:
                if self.attack_cd <= 0:
                    self.attack_cd = 0.85
                    game.hurt_player(self.contact_damage, self.name)
                direction *= 0.15

        # Simple wobble so enemies do not stack in a perfectly straight line.
        if not self.ranged:
            direction = direction.rotate(math.sin(self.anim * 1.7) * 18)

        step = direction * speed * dt
        nx, ny = move_circle(game.world, self.x, self.y, self.r, step.x, step.y)
        if (nx, ny) == (self.x, self.y) and step.length_squared() > 0.01:
            side = Vector2(-step.y, step.x)
            nx, ny = move_circle(game.world, self.x, self.y, self.r, side.x, side.y)
        self.x, self.y = nx, ny

        if self.burn > 0 and random.random() < dt * 6:
            game.particles.burst(self.x, self.y, "fire", 1, speed=18)


class Dummy(Enemy):
    kind = "dummy"

    def __init__(self, x: float, y: float):
        super().__init__(x, y, 11, 300, 0, "Training Ward", (150, 140, 120))
        self.ranged = False
        self.contact_damage = 0.0

    def update(self, dt: float, game) -> None:
        self.anim += dt
        if self.burn > 0 and random.random() < dt * 6:
            game.particles.burst(self.x, self.y, "fire", 1, speed=18)


def make_stalker(x: float, y: float) -> Enemy:
    e = Enemy(x, y, 8, 70, 62, "Husk", (176, 88, 88))
    e.contact_damage = 10.0
    return e


def make_eye(x: float, y: float) -> Enemy:
    e = Enemy(x, y, 9, 46, 44, "Watcher", (150, 110, 210))
    e.ranged = True
    e.contact_damage = 0.0
    return e
