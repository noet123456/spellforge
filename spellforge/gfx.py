"""Small drawing helpers shared by the HUD and the world renderer."""

from __future__ import annotations

import pygame

from .config import BG_PANEL, BORDER, TEXT, TEXT_DIM

_FONT_CACHE: dict[tuple, pygame.font.Font] = {}


def font(size: int, bold: bool = False, mono: bool = False) -> pygame.font.Font:
    key = (size, bold, mono)
    f = _FONT_CACHE.get(key)
    if f is None:
        if mono:
            f = pygame.font.SysFont("consolas,cascadiamono,couriernew,monospace", size, bold)
        else:
            f = pygame.font.SysFont("segoeui,trebuchetms,verdana,arial", size, bold)
        _FONT_CACHE[key] = f
    return f


def draw_text(surf: pygame.Surface, text: str, pos: tuple[float, float], size: int = 14,
              color=TEXT, bold: bool = False, mono: bool = False,
              align: str = "left", alpha: int = 255, shadow: bool = False) -> pygame.Rect:
    img = font(size, bold, mono).render(text, True, color)
    if alpha < 255:
        img.set_alpha(alpha)
    rect = img.get_rect()
    if align == "left":
        rect.topleft = (int(pos[0]), int(pos[1]))
    elif align == "center":
        rect.midtop = (int(pos[0]), int(pos[1]))
    elif align == "right":
        rect.topright = (int(pos[0]), int(pos[1]))
    elif align == "midleft":
        rect.midleft = (int(pos[0]), int(pos[1]))
    elif align == "midright":
        rect.midright = (int(pos[0]), int(pos[1]))
    if shadow:
        sh = font(size, bold, mono).render(text, True, (0, 0, 0))
        sh.set_alpha(170 if alpha == 255 else alpha // 2)
        surf.blit(sh, (rect.x + 2, rect.y + 2))
    surf.blit(img, rect)
    return rect


def text_width(text: str, size: int = 14, bold: bool = False, mono: bool = False) -> int:
    return font(size, bold, mono).size(text)[0]


def panel(surf: pygame.Surface, rect: pygame.Rect, fill=BG_PANEL, border=BORDER,
          radius: int = 8, border_width: int = 1, alpha: int = 255) -> None:
    if alpha < 255:
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, (*fill, alpha), layer.get_rect(), border_radius=radius)
        pygame.draw.rect(layer, (*border, min(255, alpha + 30)), layer.get_rect(),
                         border_width, border_radius=radius)
        surf.blit(layer, rect.topleft)
    else:
        pygame.draw.rect(surf, fill, rect, border_radius=radius)
        pygame.draw.rect(surf, border, rect, border_width, border_radius=radius)


def bar(surf: pygame.Surface, rect: pygame.Rect, value: float, maximum: float,
        color, back=(28, 30, 44), radius: int = 4, border=None) -> None:
    pygame.draw.rect(surf, back, rect, border_radius=radius)
    ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    if ratio > 0:
        inner = pygame.Rect(rect.x, rect.y, max(2, int(rect.w * ratio)), rect.h)
        pygame.draw.rect(surf, color, inner, border_radius=radius)
    if border:
        pygame.draw.rect(surf, border, rect, 1, border_radius=radius)


def wrap(text: str, width: int, size: int = 13, mono: bool = False) -> list[str]:
    f = font(size, False, mono)
    words = text.split(" ")
    lines: list[str] = []
    line = ""
    for word in words:
        trial = (line + " " + word).strip()
        if f.size(trial)[0] <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def dotted_line(surf: pygame.Surface, color, start, end, dash: int = 5, gap: int = 7,
                width: int = 1) -> None:
    import math
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 1:
        return
    ux, uy = dx / dist, dy / dist
    t = 0.0
    while t < dist:
        a = (x1 + ux * t, y1 + uy * t)
        b = (x1 + ux * min(dist, t + dash), y1 + uy * min(dist, t + dash))
        pygame.draw.line(surf, color, a, b, width)
        t += dash + gap
