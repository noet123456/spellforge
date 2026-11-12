"""Rendering of the tile world, actors, spells and effects."""

from __future__ import annotations

import math
import random

import numpy as np
import pygame

from .config import (ACCENT, ELEMENTS, GRID_H, GRID_W, TEXT, TILE, WORLD_H, WORLD_W)
from .effects import Projectile
from .entities import Dummy, Player
from .gfx import draw_text, dotted_line
from .world import (ACID, COLORS, FIRE, ICE, LAVA, MATS, PLANT, STEAM, WATER, WOOD)


def _make_vignette(w: int, h: int) -> pygame.Surface:
    xx, yy = np.mgrid[0:w, 0:h]
    dx = (xx - w / 2) / (w / 2)
    dy = (yy - h / 2) / (h / 2)
    dist = np.sqrt(dx * dx + dy * dy) * 0.78
    alpha = np.clip((dist - 0.46) * 100, 0, 100).astype(np.uint8)
    rgba = np.zeros((w, h, 4), dtype=np.uint8)
    rgba[:, :, 3] = alpha
    surf = pygame.image.frombuffer(rgba.tobytes(), (w, h), "RGBA").copy()
    return surf


class WorldRenderer:
    def __init__(self, seed: int = 4):
        self.low = pygame.Surface((GRID_W, GRID_H))
        self.glow_low = pygame.Surface((GRID_W, GRID_H))
        self.scene = pygame.Surface((WORLD_W, WORLD_H))
        self.fx = pygame.Surface((WORLD_W, WORLD_H), pygame.SRCALPHA)
        self.overlay = pygame.Surface((WORLD_W, WORLD_H), pygame.SRCALPHA)
        self.colors = np.array(COLORS, dtype=np.uint8)
        rng = np.random.default_rng(seed)
        self.shade = rng.integers(0, 9, (GRID_W, GRID_H, 1), dtype=np.uint8)
        self.vignette = _make_vignette(WORLD_W, WORLD_H)
        self.emissive = np.zeros(256, dtype=bool)
        for mid in (FIRE, LAVA, ACID):
            self.emissive[mid] = True
        self.t = 0.0

    def update(self, dt: float) -> None:
        self.t += dt

    # ------------------------------------------------------------------
    def render(self, surf: pygame.Surface, game) -> None:
        world = game.world
        mat = np.frombuffer(world.mat, dtype=np.uint8).reshape(GRID_H, GRID_W).T
        rgb = self.colors[mat].astype(np.int16)
        rgb += self.shade
        # Fire tiles flicker.
        fire = mat == FIRE
        if fire.any():
            flicker = np.random.randint(-14, 26, size=int(fire.sum()), dtype=np.int16)
            rgb[fire] = np.clip(rgb[fire] + flicker[:, None], 0, 255)
        np.clip(rgb, 0, 255, out=rgb)
        pygame.surfarray.blit_array(self.low, rgb.astype(np.uint8))

        self.scene.fill((10, 11, 18))
        pygame.transform.scale(self.low, (WORLD_W, WORLD_H), self.scene)

        # Emissive glow: scale a mask smoothly and add it.
        glow = np.zeros((GRID_W, GRID_H, 3), dtype=np.uint8)
        mask = self.emissive[mat]
        if mask.any():
            glow[mask] = self.colors[mat[mask]]
            pygame.surfarray.blit_array(self.glow_low, glow)
            big = pygame.transform.smoothscale(self.glow_low, (WORLD_W, WORLD_H))
            self.scene.blit(big, (0, 0), special_flags=pygame.BLEND_ADD)

        self._draw_fields_and_shields(game)
        self._draw_spawn_rune(game)
        self._draw_effects(game)
        self._draw_actors(game)
        if game.selected_spell is not None:
            self._draw_cursor(game)
        self.scene.blit(self.vignette, (0, 0))

        shake = game.shake_offset
        surf.blit(self.scene, (game.world_rect.x + shake[0], game.world_rect.y + shake[1]))

    # ------------------------------------------------------------------
    def _draw_fields_and_shields(self, game) -> None:
        self.overlay.fill((0, 0, 0, 0))
        for f in game.fields:
            data = ELEMENTS[f.element]
            col = data["color"]
            ratio = max(0.0, min(1.0, f.life / f.max_life))
            alpha = int(18 + 26 * ratio)
            pygame.draw.circle(self.overlay, (*col, alpha), (int(f.x), int(f.y)), int(f.radius))
            ring_a = int(70 * ratio)
            pygame.draw.circle(self.overlay, (*col, ring_a), (int(f.x), int(f.y)),
                               int(f.radius), 1)
            for k in range(3):
                ang = self.t * (0.4 + k * 0.17) + k * 2.1
                px = f.x + math.cos(ang) * f.radius * 0.72
                py = f.y + math.sin(ang) * f.radius * 0.72
                pygame.draw.circle(self.overlay, (*data["glow"], 60), (int(px), int(py)), 2)
        for v in game.vortices:
            data = ELEMENTS[v.element]
            col = data["color"]
            glow = data["glow"]
            ratio = max(0.0, min(1.0, v.life / v.max_life))
            cx, cy = int(v.x), int(v.y)
            r = max(6, int(v.radius))
            pygame.draw.circle(self.overlay, (*col, 20), (cx, cy), r)
            pygame.draw.circle(self.overlay, (*col, int(35 + 55 * ratio)), (cx, cy), r, 2)
            pygame.draw.circle(self.overlay, (*glow, int(16 + 30 * ratio)), (cx, cy),
                               int(r * 0.62), 1)
            for k in range(6):
                prev = None
                for s in range(10):
                    a = v.angle * v.spin + k * math.tau / 6 + s * 0.20 * v.spin
                    rr = r * (0.14 + 0.86 * s / 9)
                    px = v.x + math.cos(a) * rr
                    py = v.y + math.sin(a) * rr
                    if prev is not None:
                        alpha = int((60 + 105 * ratio) * (0.30 + 0.70 * s / 9))
                        pygame.draw.line(self.overlay, (*glow, alpha), prev, (px, py), 3)
                    prev = (px, py)
            pygame.draw.circle(self.overlay, (*glow, int(70 + 70 * ratio)), (cx, cy),
                               max(2, r // 8))
            pygame.draw.circle(self.overlay, (255, 255, 255, int(120 * ratio)), (cx, cy), 1)
        for s in game.shields:
            col = ELEMENTS[s.element]["color"]
            ratio = max(0.0, min(1.0, s.life / s.max_life))
            alpha = int(40 + 55 * ratio)
            pygame.draw.circle(self.overlay, (*col, alpha), (int(s.owner.x), int(s.owner.y)),
                               int(s.radius), 2)
            pygame.draw.circle(self.overlay, (*col, 16), (int(s.owner.x), int(s.owner.y)),
                               int(s.radius))
            ang = s.phase + self.t * 1.8
            for k in range(6):
                a = ang + k * math.tau / 6
                px = s.owner.x + math.cos(a) * s.radius
                py = s.owner.y + math.sin(a) * s.radius
                pygame.draw.circle(self.overlay, (*col, 150), (int(px), int(py)), 2)
        self.scene.blit(self.overlay, (0, 0))

    def _draw_spawn_rune(self, game) -> None:
        sx, sy = game.spawn_point
        col = ACCENT
        self.overlay.fill((0, 0, 0, 0))
        pulse = 0.55 + 0.45 * math.sin(self.t * 2.0)
        pygame.draw.circle(self.overlay, (*col, 34), (int(sx), int(sy)), 22, 1)
        pygame.draw.circle(self.overlay, (*col, int(58 * pulse)), (int(sx), int(sy)), 16, 1)
        for k in range(6):
            a = self.t * 0.55 + k * math.tau / 6
            px = sx + math.cos(a) * 19
            py = sy + math.sin(a) * 19
            pygame.draw.circle(self.overlay, (*col, 120), (int(px), int(py)), 2)
            px2 = sx + math.cos(a + math.pi) * 12
            py2 = sy + math.sin(a + math.pi) * 12
            pygame.draw.circle(self.overlay, (*col, 50), (int(px2), int(py2)), 1)
        self.scene.blit(self.overlay, (0, 0))

    def _draw_effects(self, game) -> None:
        self.fx.fill((0, 0, 0, 0))
        for b in game.beams:
            ratio = max(0.0, b.life / b.max_life)
            a = int(220 * ratio)
            width = max(1, int(b.width * (0.4 + ratio)))
            pygame.draw.line(self.fx, (*b.color, a // 3), (b.x1, b.y1), (b.x2, b.y2), width + 4)
            pygame.draw.line(self.fx, (*b.color, a), (b.x1, b.y1), (b.x2, b.y2), width)
            pygame.draw.line(self.fx, (255, 255, 255, a), (b.x1, b.y1), (b.x2, b.y2),
                             max(1, width // 3))
        for r in game.rings:
            ratio = max(0.0, r.life / r.max_life)
            radius = int(r.radius + (r.max_radius - r.radius) * (1.0 - ratio))
            alpha = int(190 * ratio)
            pygame.draw.circle(self.fx, (*r.color, alpha), (int(r.x), int(r.y)),
                               max(1, radius), max(1, r.width))
        for p in game.particles.items:
            ratio = max(0.0, p.life / p.max_life)
            alpha = int(255 * min(1.0, ratio * 1.5))
            if alpha <= 3:
                continue
            r = max(1, int(p.size * (0.4 + ratio * 0.8)))
            pygame.draw.circle(self.fx, (*p.color, int(alpha * 0.22)),
                               (int(p.x), int(p.y)), r + 2)
            pygame.draw.circle(self.fx, (*p.color, alpha), (int(p.x), int(p.y)), r)

        for proj in game.projectiles:
            base = ELEMENTS[proj.element]["color"]
            glow = ELEMENTS[proj.element]["glow"]
            r = max(2, int(proj.r))
            pygame.draw.circle(self.fx, (*glow, 60), (int(proj.x), int(proj.y)), r + 5)
            pygame.draw.circle(self.fx, (*base, 120), (int(proj.x), int(proj.y)), r + 2)

        self.scene.blit(self.fx, (0, 0), special_flags=pygame.BLEND_ADD)

        # Solid projectile cores on top of the additive layer.
        for proj in game.projectiles:
            base = ELEMENTS[proj.element]["color"]
            r = max(2, int(proj.r))
            pygame.draw.circle(self.scene, base, (int(proj.x), int(proj.y)), r)
            pygame.draw.circle(self.scene, (255, 255, 255), (int(proj.x), int(proj.y)),
                               max(1, r // 2))
            if proj.hostile:
                pygame.draw.circle(self.scene, (255, 110, 110), (int(proj.x), int(proj.y)),
                                   r + 1, 1)

    def _draw_actors(self, game) -> None:
        for enemy in game.enemies:
            if not enemy.alive:
                continue
            self._draw_enemy(enemy, game)
        self._draw_player(game.player, game)

        for f in game.floaters:
            ratio = max(0.0, f.life / f.max_life)
            alpha = int(255 * min(1.0, ratio * 2.0))
            draw_text(self.scene, f.text, (f.x, f.y), f.size, f.color,
                      bold=True, align="center", alpha=alpha, shadow=True)

    def _draw_player(self, p: Player, game) -> None:
        if p.invuln > 0 and int(p.invuln * 24) % 2 == 0:
            return
        x, y = int(p.x), int(p.y)
        accent = ELEMENTS[game.selected_element]["color"]
        bob = math.sin(p.walk_phase) * 1.2 if p.dash_v.length_squared() < 10 else 0
        y = int(y + bob)
        # Shadow
        shadow = pygame.Surface((26, 16), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 90), shadow.get_rect())
        self.scene.blit(shadow, (x - 13, int(p.y) + 6))
        # Robe
        pygame.draw.circle(self.scene, (44, 46, 72), (x, y + 1), int(p.r) + 1)
        pygame.draw.circle(self.scene, (64, 70, 110), (x, y), int(p.r))
        pygame.draw.circle(self.scene, accent, (x, y), int(p.r), 1)
        # Hat brim + tip pointing at the cursor
        aim = p.aim
        tip = (x + aim.x * 15, y + aim.y * 15)
        perp = (-aim.y, aim.x)
        brim_l = (x + perp[0] * 8 - aim.x * 2, y + perp[1] * 8 - aim.y * 2)
        brim_r = (x - perp[0] * 8 - aim.x * 2, y - perp[1] * 8 - aim.y * 2)
        pygame.draw.polygon(self.scene, (30, 30, 48), [brim_l, brim_r, tip])
        pygame.draw.polygon(self.scene, accent, [brim_l, brim_r, tip], 1)
        pygame.draw.circle(self.scene, (18, 18, 30), (x, y), 3)
        # Staff and glowing tip
        sx = x - aim.x * 2 + perp[0] * 9
        sy = y - aim.y * 2 + perp[1] * 9
        ex = sx + aim.x * 12
        ey = sy + aim.y * 12
        pygame.draw.line(self.scene, (120, 100, 70), (sx, sy), (ex, ey), 2)
        pygame.draw.circle(self.scene, accent, (int(ex), int(ey)), 2)

    def _draw_enemy(self, e, game) -> None:
        x, y = int(e.x), int(e.y)
        if isinstance(e, Dummy):
            pygame.draw.circle(self.scene, (70, 60, 48), (x, y), int(e.r) + 2)
            pygame.draw.circle(self.scene, (150, 132, 104), (x, y), int(e.r))
            pygame.draw.circle(self.scene, (90, 74, 56), (x, y), int(e.r), 2)
            pygame.draw.circle(self.scene, (214, 190, 140), (x, y), 4, 1)
            pygame.draw.line(self.scene, (214, 190, 140), (x - 5, y), (x + 5, y), 1)
            pygame.draw.line(self.scene, (214, 190, 140), (x, y - 5), (x, y + 5), 1)
        elif getattr(e, "ranged", False):
            bob = math.sin(e.anim * 2.2) * 2
            yy = int(y + bob)
            pygame.draw.circle(self.scene, (40, 26, 60), (x, yy), int(e.r) + 2)
            pygame.draw.circle(self.scene, e.color, (x, yy), int(e.r))
            pygame.draw.circle(self.scene, (240, 232, 255), (x, yy), int(e.r) - 2)
            look = pygame.Vector2(game.player.x - e.x, game.player.y - e.y)
            if look.length_squared() > 0:
                look = look.normalize()
            pygame.draw.circle(self.scene, (24, 16, 34),
                               (int(x + look.x * 3), int(yy + look.y * 3)), 3)
        else:
            bob = math.sin(e.anim * 8) * 1.2
            yy = int(y + bob)
            pygame.draw.circle(self.scene, (44, 24, 26), (x, yy), int(e.r) + 1)
            points = []
            for k in range(7):
                a = e.anim * 0.6 + k * math.tau / 7
                rr = e.r + (2 if k % 2 == 0 else -1)
                points.append((x + math.cos(a) * rr, yy + math.sin(a) * rr))
            pygame.draw.polygon(self.scene, e.color, points)
            pygame.draw.circle(self.scene, (255, 210, 130), (x, yy), 2)

        if e.burn > 0:
            pygame.draw.circle(self.scene, (255, 120, 40), (x, y), int(e.r) + 3, 1)
        elif e.chill > 0:
            pygame.draw.circle(self.scene, (140, 220, 255), (x, y), int(e.r) + 3, 1)
        elif e.poison > 0:
            pygame.draw.circle(self.scene, (130, 220, 90), (x, y), int(e.r) + 3, 1)

        if e.hp < e.max_hp and not isinstance(e, Dummy) or (isinstance(e, Dummy) and e.hp < e.max_hp):
            w = 30
            rect = pygame.Rect(x - w // 2, int(e.y - e.r - 9), w, 3)
            pygame.draw.rect(self.scene, (20, 18, 26), rect)
            ratio = max(0.0, e.hp / e.max_hp)
            pygame.draw.rect(self.scene, (220, 92, 92),
                             (rect.x, rect.y, max(1, int(w * ratio)), 3))

    def _draw_cursor(self, game) -> None:
        x, y = game.mouse_world
        elem = game.selected_element
        col = ELEMENTS[elem]["color"]
        p = game.player
        if math.hypot(x - p.x, y - p.y) > 30:
            dotted_line(self.scene, (*col, 40), (p.x, p.y), (x, y), dash=4, gap=9, width=1)
        pygame.draw.circle(self.scene, col, (int(x), int(y)), 7, 1)
        pygame.draw.circle(self.scene, col, (int(x), int(y)), 2)
        for dx, dy in ((10, 0), (-10, 0), (0, 10), (0, -10)):
            pygame.draw.line(self.scene, col, (x + dx * 0.8, y + dy * 0.8),
                             (x + dx, y + dy), 1)
