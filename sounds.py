"""
sounds.py — Procedural sound effects using pygame.mixer.

Generates simple waveforms for game events without requiring any
external audio files.  All sounds are synthesized at startup.

Uses numpy to create waveforms and pygame.sndarray to convert them.
"""

from __future__ import annotations

import math
import numpy as np
import pygame


def _make_sound(samples: np.ndarray) -> pygame.mixer.Sound:
    """Convert a float64 numpy array [-1, 1] to a pygame Sound."""
    # Ensure stereo
    if samples.ndim == 1:
        samples = np.column_stack([samples, samples])
    # Convert to 16-bit integers
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    return pygame.sndarray.make_sound(int_samples)


def _sine(freq: float, duration: float, volume: float = 0.3) -> np.ndarray:
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    wave = np.sin(2 * math.pi * freq * t) * volume
    # Fade out last 20%
    fade_len = int(len(wave) * 0.2)
    if fade_len > 0:
        wave[-fade_len:] *= np.linspace(1, 0, fade_len)
    return wave


def _noise(duration: float, volume: float = 0.15) -> np.ndarray:
    sr = 44100
    n = int(sr * duration)
    wave = np.random.uniform(-1, 1, n) * volume
    # Fade out
    fade_len = int(n * 0.3)
    if fade_len > 0:
        wave[-fade_len:] *= np.linspace(1, 0, fade_len)
    return wave


class SoundManager:
    """Manages all procedural sound effects."""

    def __init__(self) -> None:
        self.enabled: bool = True
        self._sounds: dict = {}
        self._try_init()

    def _try_init(self) -> None:
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._generate_all()
        except Exception:
            self.enabled = False

    def _generate_all(self) -> None:
        """Pre-generate all sound effects."""
        # Build complete — ascending chime
        self._sounds["build_complete"] = self._chime([523, 659, 784], 0.12, 0.25)

        # Build start — short thud
        self._sounds["build_start"] = self._thud(0.1, 0.3)

        # Place building — click
        self._sounds["place"] = self._click(0.05, 0.2)

        # Attack hit — noise burst
        self._sounds["hit"] = self._noise_hit(0.08, 0.2)

        # Enemy death — descending tone
        self._sounds["enemy_death"] = self._descend(400, 150, 0.15, 0.25)

        # Villager death — low tone
        self._sounds["villager_death"] = self._descend(250, 100, 0.25, 0.3)

        # Research complete — bright arpeggio
        self._sounds["research"] = self._chime([659, 784, 988, 1175], 0.08, 0.2)

        # Achievement — fanfare
        self._sounds["achievement"] = self._chime([523, 659, 784, 1047], 0.1, 0.3)

        # Raid warning — alarm
        self._sounds["raid"] = self._alarm(0.3, 0.2)

        # Button click — soft tick
        self._sounds["click"] = self._click(0.03, 0.15)

        # Error — low buzz
        self._sounds["error"] = self._buzz(0.15, 0.15)

        # Upgrade — triple ascending
        self._sounds["upgrade"] = self._chime([440, 554, 659], 0.12, 0.25)

        # Trading — coin sound
        self._sounds["trade"] = self._coin(0.2, 0.25)

        # Defeat — low descending
        self._sounds["defeat"] = self._descend(300, 80, 0.6, 0.35)

        # Victory — fanfare
        self._sounds["victory"] = self._chime([523, 659, 784, 1047, 1319], 0.12, 0.3)

    # ── Sound generators ──────────────────────────

    def _chime(self, freqs: list, note_len: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        parts = []
        for f in freqs:
            parts.append(_sine(f, note_len, vol))
        return _make_sound(np.concatenate(parts))

    def _thud(self, duration: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        n = int(sr * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        # Low frequency + noise
        wave = (np.sin(2 * math.pi * 80 * t) * 0.7 + np.random.uniform(-0.3, 0.3, n)) * vol
        # Quick decay
        decay = np.exp(-t * 30)
        wave *= decay
        return _make_sound(wave)

    def _click(self, duration: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        n = int(sr * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        wave = np.sin(2 * math.pi * 1200 * t) * vol * np.exp(-t * 60)
        return _make_sound(wave)

    def _noise_hit(self, duration: float, vol: float) -> pygame.mixer.Sound:
        base = _noise(duration, vol)
        sr = 44100
        n = len(base)
        t = np.linspace(0, duration, n, endpoint=False)
        # Add a low thud underneath
        thud = np.sin(2 * math.pi * 100 * t) * vol * 0.5 * np.exp(-t * 25)
        return _make_sound(base + thud)

    def _descend(self, start_freq: float, end_freq: float,
                 duration: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        n = int(sr * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        # Frequency sweeps from start to end
        freq = np.linspace(start_freq, end_freq, n)
        phase = np.cumsum(2 * math.pi * freq / sr)
        wave = np.sin(phase) * vol
        # Fade
        fade = np.linspace(1, 0, n)
        wave *= fade
        return _make_sound(wave)

    def _alarm(self, duration: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        n = int(sr * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        # Alternating two tones
        freq = np.where(np.sin(2 * math.pi * 6 * t) > 0, 440, 550)
        phase = np.cumsum(2 * math.pi * freq / sr)
        wave = np.sin(phase) * vol
        return _make_sound(wave)

    def _buzz(self, duration: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        n = int(sr * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        wave = (np.sin(2 * math.pi * 90 * t) + 0.3 * np.sin(2 * math.pi * 180 * t)) * vol
        wave *= np.exp(-t * 8)
        return _make_sound(wave)

    def _coin(self, duration: float, vol: float) -> pygame.mixer.Sound:
        sr = 44100
        n = int(sr * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        # High metallic ping
        wave = np.sin(2 * math.pi * 2400 * t) * vol * np.exp(-t * 12)
        wave += np.sin(2 * math.pi * 3200 * t) * vol * 0.5 * np.exp(-t * 15)
        return _make_sound(wave)

    # ── Playback ──────────────────────────────────

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        snd = self._sounds.get(name)
        if snd:
            try:
                snd.play()
            except Exception:
                pass

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled