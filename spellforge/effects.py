"""Visual and transient combat objects."""

from __future__ import annotations

import math
import random

from pygame import Vector2

from .config import ELEMENTS


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size", "drag", "glow", "kind")

    def __init__(self, x, y, vx, vy, life, color, size, drag=3.0, glow=True, kind="spark"):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size
        self.drag = drag
        self.glow = glow
        self.kind = kind


class ParticleSystem:
    def __init__(self):
        self.items: list[Particle] = []

    def add(self, p: Particle) -> None:
        if len(self.items) > 1100:
            del self.items[:160]
        self.items.append(p)

    def burst(self, x, y, element, count=6, speed=90, life=0.55, size=2.4) -> None:
        data = ELEMENTS.get(element, ELEMENTS["arcane"])
        base = data["color"]
        for _ in range(count):
            ang = random.random() * math.tau
            spd = speed * (0.25 + random.random() * 0.9)
            col = base
            if element == "fire" and random.random() < 0.5:
                col = (255, 210, 120)
            if element == "lightning" and random.random() < 0.5:
                col = (255, 255, 235)
            self.add(Particle(x, y, math.cos(ang) * spd, math.sin(ang) * spd,
                              life * (0.6 + random.random() * 0.8), col,
                              size * (0.6 + random.random() * 0.8),
                              drag=4.0, glow=True))

    def dust(self, x, y, count=2) -> None:
        for _ in range(count):
            self.add(Particle(x + random.uniform(-3, 3), y, random.uniform(-12, 12), -random.uniform(3, 14),
                              0.4, (110, 108, 104), 1.6, drag=2.0, glow=False, kind="dust"))

    def trail(self, x, y, element, size=1.8) -> None:
        data = ELEMENTS.get(element, ELEMENTS["arcane"])
        col = data["color"]
        self.add(Particle(x, y, random.uniform(-8, 8), random.uniform(-8, 8), 0.3, col, size,
                          drag=3.0, glow=True))

    def add_spark(self, x, y, color, size=2.0) -> None:
        self.add(Particle(x + random.uniform(-2, 2), y + random.uniform(-2, 2),
                          random.uniform(-40, 40), random.uniform(-40, 40),
                          0.25 + random.random() * 0.2, color,
                          size * (0.5 + random.random()), drag=6.0, glow=True))

    def update(self, dt: float) -> None:
        alive = []
        for p in self.items:
            p.life -= dt
            if p.life <= 0:
                continue
            damp = max(0.0, 1.0 - p.drag * dt)
            p.vx *= damp
            p.vy *= damp
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self.items = alive


class Projectile:
    __slots__ = ("x", "y", "vx", "vy", "r", "element", "damage", "power", "owner", "hostile",
                 "pierce", "homing", "life", "on_hit", "on_expire", "dead", "trail", "hits",
                 "spin", "size")

    def __init__(self, x, y, vx, vy, r, element, damage, owner=None, hostile=False,
                 pierce=0, homing=0.0, life=2.5, power=1.0, on_hit=None, on_expire=None,
                 size=1.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.r = r
        self.element = element
        self.damage = damage
        self.power = power
        self.owner = owner
        self.hostile = hostile
        self.pierce = pierce
        self.homing = homing
        self.life = life
        self.on_hit = on_hit
        self.on_expire = on_expire
        self.dead = False
        self.trail = 0.0
        self.hits: set[int] = set()
        self.spin = random.random() * 6.28
        self.size = size


class Field:
    __slots__ = ("x", "y", "radius", "element", "power", "life", "max_life", "tick", "owner", "ticks")

    def __init__(self, x, y, radius, element, power, life, owner=None):
        self.x = x
        self.y = y
        self.radius = radius
        self.element = element
        self.power = power
        self.life = life
        self.max_life = life
        self.tick = 0.0
        self.owner = owner
        self.ticks = 0


class Vortex:
    __slots__ = ("x", "y", "radius", "element", "power", "life", "max_life",
                 "pull", "spin", "angle", "tick", "phase")

    def __init__(self, x, y, radius, element, power, life, pull=1.0, spin=1):
        self.x = x
        self.y = y
        self.radius = radius
        self.element = element
        self.power = power
        self.life = life
        self.max_life = life
        self.pull = pull
        self.spin = 1 if spin >= 0 else -1
        self.angle = random.random() * math.tau
        self.tick = 0.0
        self.phase = random.random() * math.tau


class Shield:
    __slots__ = ("owner", "radius", "element", "power", "life", "max_life", "flash", "phase")

    def __init__(self, owner, radius, element, power, life):
        self.owner = owner
        self.radius = radius
        self.element = element
        self.power = power
        self.life = life
        self.max_life = life
        self.flash = 0.0
        self.phase = random.random() * 6.28


class FloatingText:
    __slots__ = ("x", "y", "text", "color", "life", "max_life", "vy", "size")

    def __init__(self, x, y, text, color, size=14, life=0.8):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.life = life
        self.max_life = life
        self.vy = -32.0
        self.size = size


class Ring:
    __slots__ = ("x", "y", "radius", "max_radius", "life", "max_life", "color", "width")

    def __init__(self, x, y, radius, max_radius, life, color, width=2):
        self.x = x
        self.y = y
        self.radius = radius
        self.max_radius = max_radius
        self.life = life
        self.max_life = life
        self.color = color
        self.width = width


class Beam:
    __slots__ = ("x1", "y1", "x2", "y2", "color", "life", "max_life", "width")

    def __init__(self, x1, y1, x2, y2, color, life=0.18, width=3):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.color = color
        self.life = life
        self.max_life = life
        self.width = width
