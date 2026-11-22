"""
weather.py — Weather system with Markov-chain transitions, particle effects,
and simulation multipliers.

Weather changes every WEATHER_MIN_TICKS..WEATHER_MAX_TICKS simulation ticks
using weighted random transitions (WEATHER_TRANSITION table).
"""

from __future__ import annotations

import random
from typing import List, Tuple, TYPE_CHECKING

import pygame

from config import (
    Weather, WEATHER_EFFECTS, WEATHER_TRANSITION,
    WEATHER_MIN_TICKS, WEATHER_MAX_TICKS,
)

if TYPE_CHECKING:
    pass


# ════════════════════════════════════════════════
#  Weather particle
# ════════════════════════════════════════════════
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "color")

    def __init__(self, x: float, y: float, vx: float, vy: float,
                 life: float, size: int, color: Tuple[int, int, int]) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.size = size
        self.color = color


# ════════════════════════════════════════════════
#  WeatherManager
# ════════════════════════════════════════════════
class WeatherManager:
    """Controls weather state transitions and manages visual particles."""

    def __init__(self, screen_w: int, screen_h: int) -> None:
        self.current: Weather = Weather.CLEAR
        self._timer: int = random.randint(WEATHER_MIN_TICKS, WEATHER_MAX_TICKS)
        self.particles: List[Particle] = []
        self.screen_w = screen_w
        self.screen_h = screen_h

    # ── simulation tick ──────────────────────────
    def tick(self) -> None:
        """Call once per simulation tick to advance weather state."""
        self._timer -= 1
        if self._timer <= 0:
            self._transition()
            self._timer = random.randint(WEATHER_MIN_TICKS, WEATHER_MAX_TICKS)

    def _transition(self) -> None:
        weights = WEATHER_TRANSITION[self.current]
        options = [w for w, _ in weights]
        probs = [p for _, p in weights]
        self.current = random.choices(options, weights=probs, k=1)[0]

    # ── properties ───────────────────────────────
    @property
    def move_mult(self) -> float:
        return WEATHER_EFFECTS[self.current]["move_mult"]

    @property
    def farm_mult(self) -> float:
        return WEATHER_EFFECTS[self.current]["farm_mult"]

    @property
    def combat_mult(self) -> float:
        return WEATHER_EFFECTS[self.current]["combat_mult"]

    @property
    def label(self) -> str:
        return WEATHER_EFFECTS[self.current]["label"]

    # ── rendering (called every frame) ───────────
    def update_particles(self, dt: float) -> None:
        """Spawn and move particles; called at render FPS."""
        self._spawn(dt)
        alive: List[Particle] = []
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt
            if p.life > 0 and 0 <= p.x <= self.screen_w and 0 <= p.y <= self.screen_h:
                alive.append(p)
        self.particles = alive

    def _spawn(self, dt: float) -> None:
        if self.current == Weather.CLEAR:
            return
        # Spawn rate depends on weather
        if self.current == Weather.RAIN:
            count = int(120 * dt)
            for _ in range(count):
                self.particles.append(Particle(
                    x=random.uniform(0, self.screen_w),
                    y=random.uniform(-20, -5),
                    vx=random.uniform(-20, 20),
                    vy=random.uniform(350, 500),
                    life=random.uniform(0.8, 1.5),
                    size=random.choice([1, 1, 2]),
                    color=(140, 170, 220),
                ))
        elif self.current == Weather.STORM:
            count = int(250 * dt)
            for _ in range(count):
                self.particles.append(Particle(
                    x=random.uniform(-50, self.screen_w),
                    y=random.uniform(-30, -5),
                    vx=random.uniform(80, 180),
                    vy=random.uniform(400, 650),
                    life=random.uniform(0.5, 1.0),
                    size=random.choice([1, 2, 2]),
                    color=(170, 190, 230),
                ))
        elif self.current == Weather.SNOW:
            count = int(60 * dt)
            for _ in range(count):
                self.particles.append(Particle(
                    x=random.uniform(0, self.screen_w),
                    y=random.uniform(-10, -2),
                    vx=random.uniform(-30, 30),
                    vy=random.uniform(40, 100),
                    life=random.uniform(2.0, 4.0),
                    size=random.choice([2, 2, 3]),
                    color=(230, 235, 245),
                ))

    def draw_particles(self, surface: pygame.Surface) -> None:
        for p in self.particles:
            alpha = min(1.0, p.life / (p.max_life * 0.3))
            c = tuple(int(v * alpha) for v in p.color)
            if p.size <= 1:
                surface.set_at((int(p.x), int(p.y)), c)
            else:
                pygame.draw.circle(surface, c, (int(p.x), int(p.y)), p.size)

    def draw_overlay(self, surface: pygame.Surface) -> None:
        """Draw a full-screen tint for storm/dark weather."""
        if self.current == Weather.STORM:
            ov = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            ov.fill((10, 10, 30, 25))
            surface.blit(ov, (0, 0))
        elif self.current == Weather.RAIN:
            ov = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            ov.fill((20, 30, 50, 12))
            surface.blit(ov, (0, 0))

    def resize(self, w: int, h: int) -> None:
        self.screen_w = w
        self.screen_h = h