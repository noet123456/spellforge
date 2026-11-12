"""Tiny procedural sound effects (no asset files required)."""

from __future__ import annotations

import math

import numpy as np
import pygame


class Audio:
    def __init__(self):
        self.ok = False
        self.muted = False
        self.last: dict[str, float] = {}
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            info = pygame.mixer.get_init()
            if info is None:
                return
            self.rate, _, self.channels = info
            self._build()
            self.ok = True
        except Exception:
            self.ok = False

    # ------------------------------------------------------------------
    def _arr(self, y: np.ndarray) -> np.ndarray:
        y = np.clip(y, -1.0, 1.0)
        pcm = (y * 32767).astype(np.int16)
        if self.channels > 1:
            pcm = np.repeat(pcm[:, None], self.channels, axis=1)
        return pcm

    def _sweep(self, f0: float, f1: float, dur: float, vol: float = 0.35,
               noise: float = 0.0, decay: float = 5.0) -> np.ndarray:
        n = max(8, int(self.rate * dur))
        t = np.arange(n) / self.rate
        freq = np.linspace(f0, f1, n)
        phase = np.cumsum(2 * math.pi * freq / self.rate)
        y = np.sin(phase)
        if noise:
            y = (1 - noise) * y + noise * np.random.uniform(-1, 1, n)
        y *= np.exp(-decay * t) * vol
        return self._arr(y)

    def _chord(self, freqs: list[float], dur: float, vol: float = 0.25,
               decay: float = 4.0) -> np.ndarray:
        n = max(8, int(self.rate * dur))
        t = np.arange(n) / self.rate
        y = np.zeros(n)
        for i, f in enumerate(freqs):
            start = int(self.rate * 0.055 * i)
            if start >= n:
                break
            tt = t[:n - start]
            y[start:] += 0.6 * np.sin(2 * math.pi * f * tt) * np.exp(-decay * tt)
        y *= vol
        return self._arr(y)

    def _build(self) -> None:
        np.random.seed(3)
        self.sounds = {
            "cast": pygame.mixer.Sound(buffer=self._sweep(720, 260, 0.16, 0.30, 0.2, 7)),
            "boom": pygame.mixer.Sound(buffer=self._sweep(150, 42, 0.38, 0.55, 0.45, 5)),
            "zap": pygame.mixer.Sound(buffer=self._sweep(1900, 380, 0.15, 0.28, 0.7, 9)),
            "freeze": pygame.mixer.Sound(buffer=self._sweep(2300, 800, 0.26, 0.22, 0.08, 5)),
            "heal": pygame.mixer.Sound(buffer=self._chord([523.25, 659.25, 783.99], 0.36, 0.28)),
            "hit": pygame.mixer.Sound(buffer=self._sweep(240, 90, 0.11, 0.45, 0.6, 11)),
            "error": pygame.mixer.Sound(buffer=self._sweep(220, 150, 0.18, 0.25, 0.1, 4)),
            "ui": pygame.mixer.Sound(buffer=self._sweep(900, 1150, 0.06, 0.18, 0.0, 10)),
        }

    # ------------------------------------------------------------------
    def play(self, name: str, volume: float = 1.0) -> None:
        if not self.ok or self.muted:
            return
        now = pygame.time.get_ticks() * 0.001
        if now - self.last.get(name, -1.0) < 0.045:
            return
        self.last[name] = now
        sound = self.sounds.get(name)
        if sound is None:
            return
        sound.set_volume(max(0.0, min(1.0, volume)))
        sound.play()
