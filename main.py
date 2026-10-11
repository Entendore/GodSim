"""
God Simulator — Phase 1 + 2 + 3 + 4 + 5 + 6 + 7
==============================================
Grid · camera · terrain painting · minimap · procedural gen ·
entity manager · FSM villager AI · decoupled sim tick ·
A* pathfinding · day/night cycle · hunger/food · buildable
structures · event log · auto-population ·
weather system · stone mining · enemy raids · combat · guards · walls ·
technology tree · trading · villager roles ·
building upgrades · achievements · sound effects · game-over/victory ·
diplomacy · AI villages · alliances · war

Controls (Phase 1):
    WASD / Arrows       — pan camera
    Middle-click + drag — pan camera
    Edge of screen      — auto-pan
    Scroll wheel        — zoom
    Left-click/drag     — paint terrain (or place building in build mode)
    Right-click/drag    — erase to GRASS
    1-6                 — select tile type
    [ / ]               — brush size
    B                   — brush shape
    X                   — grid lines
    G                   — generate terrain
    F5 / F9             — save / load

Controls (Phase 2):
    V                   — spawn villager
    H                   — place town hall
    Space               — pause / unpause

Controls (Phase 3):
    7 / 8 / 9           — select building (House / Farm / Storage)
    Escape (in build)   — cancel build mode
    Left-click (build)  — place building

Controls (Phase 4):
    0                   — select Wall
    -                   — select Gate
    G (on selected vil) — toggle guard duty
    N                   — trigger test raid

Controls (Phase 5):
    R (on selected vil) — cycle role
    T                   — toggle tech tree panel
    1-8 (in tech tree)  — select & start research
    C/Q/E               — accept trade offers 1/2/3

Controls (Phase 6):
    U (on selected bld) — upgrade building
    P                   — toggle statistics panel
    M                   — toggle sound on/off
    Backspace          — restart game after game over

Controls (Phase 7):
    D                   — toggle diplomacy panel
    1-4 (in diplomacy) — select village
    G                   — send gift to selected village
    T                   — propose trade pact
    A                   — propose alliance
    W                   — declare war
    K                   — propose peace
    J                   — accept pending proposal
    F                   — reject pending proposal
"""

from __future__ import annotations

import sys
import math
import time
import os
import numpy as np
from collections import deque
from typing import Optional, Tuple, Dict, List

import pygame

from config import (
    TILE_SIZE, WORLD_W, WORLD_H,
    TileType, TILE_PALETTE, SAVE_PATH, WALKABLE_TILES,
    BuildingType, BUILDING_DEFS, BUILD_BAR_ORDER,
    DAY_LENGTH, DAWN_END, DAY_END, DUSK_END,
    Weather, Tech, TECH_DEFS, Role, ROLE_NAMES,
)
from entities import Entity, Building, EntityManager
from simulation import (
    SimulationManager, EventLog,
    get_day_phase, get_night_tint,
)
from villager import draw_villagers, STATE_LABELS
from enemy import draw_enemies
from achievements import (
    AchievementManager, ACHIEVEMENT_DEFS, ACHIEVEMENT_ORDER,
)
from buildings_upgrade import can_upgrade, start_upgrade, UPGRADEABLE, get_upgrade_cost
from diplomacy import draw_diplomacy_panel

SCREEN_W, SCREEN_H = 1280, 800
FPS = 60
EDGE_SCROLL_ZONE = 12
EDGE_SCROLL_SPEED = 450.0
MINIMAP_W = 200
MINIMAP_H = 200
MINIMAP_MARGIN = 10


# ──────────────────────────────────────────────
# Noise generator
# ──────────────────────────────────────────────
class NoiseGenerator:
    def __init__(self, seed: int = 42) -> None:
        rng = np.random.RandomState(seed)
        self._perm = rng.permutation(256).astype(np.int32)

    def _fade(self, t):
        return t * t * t * (t * (t * 6 - 15) + 10)

    def _lerp(self, a, b, t):
        return a + (b - a) * t

    def generate(self, w, h, scale=0.015, octaves=6, persistence=0.5, lacunarity=2.0):
        xs = np.arange(w, dtype=np.float64)
        ys = np.arange(h, dtype=np.float64)
        gx, gy = np.meshgrid(xs * scale, ys * scale)
        result = np.zeros((h, w), dtype=np.float64)
        amp, freq, max_v = 1.0, 1.0, 0.0
        for _ in range(octaves):
            ix = np.floor(gx * freq).astype(np.int32) & 255
            iy = np.floor(gy * freq).astype(np.int32) & 255
            fx = (gx * freq) - np.floor(gx * freq)
            fy = (gy * freq) - np.floor(gy * freq)
            u, v = self._fade(fx), self._fade(fy)
            p = self._perm
            aa, ab = p[p[ix] + iy], p[p[ix] + iy + 1]
            ba, bb = p[p[ix + 1] + iy], p[p[ix + 1] + iy + 1]
            _v = lambda h: (h & 0xFF).astype(np.float64) / 255.0
            result += self._lerp(self._lerp(_v(aa), _v(ba), u),
                                 self._lerp(_v(ab), _v(bb), u), v) * amp
            max_v += amp; amp *= persistence; freq *= lacunarity
        return (result / max_v).astype(np.float32)


def generate_terrain(world, seed=None):
    if seed is None:
        seed = int(time.time() * 1000) % (2**31)
    print(f"[World] Generating terrain seed={seed}")
    noise = NoiseGenerator(seed)
    hm = noise.generate(WORLD_W, WORLD_H, 0.012, 6, 0.50, 2.0)
    moisture = NoiseGenerator(seed + 777).generate(WORLD_W, WORLD_H, 0.018, 4, 0.45, 2.2)
    tiles = np.full_like(world.tiles, TileType.GRASS, dtype=np.uint8)
    tiles[hm < 0.28] = TileType.WATER
    tiles[(hm >= 0.28) & (hm < 0.33)] = TileType.SAND
    tiles[(hm >= 0.33) & (hm < 0.65) & (moisture > 0.55)] = TileType.FOREST
    tiles[hm >= 0.75] = TileType.MOUNTAIN
    tiles[hm >= 0.90] = TileType.LAVA
    world.tiles[:] = tiles
    world.variation = np.random.randint(0, 4, (world.h, world.w), dtype=np.uint8)


# ──────────────────────────────────────────────
# World
# ──────────────────────────────────────────────
class World:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.tiles = np.full((h, w), TileType.GRASS, dtype=np.uint8)
        self.variation = np.random.randint(0, 4, (h, w), dtype=np.uint8)
        self._dirty = True

    def get(self, tx, ty):
        if 0 <= tx < self.w and 0 <= ty < self.h:
            return TileType(int(self.tiles[ty, tx]))
        return TileType.GRASS

    def set(self, tx, ty, t):
        if 0 <= tx < self.w and 0 <= ty < self.h:
            self.tiles[ty, tx] = t
            self.variation[ty, tx] = np.random.randint(0, 4)

    def in_bounds(self, tx, ty):
        return 0 <= tx < self.w and 0 <= ty < self.h

    def paint_rect(self, cx, cy, radius, tile):
        y0, y1 = max(cy - radius, 0), min(cy + radius + 1, self.h)
        x0, x1 = max(cx - radius, 0), min(cx + radius + 1, self.w)
        if y1 <= y0 or x1 <= x0: return
        self.tiles[y0:y1, x0:x1] = tile
        self.variation[y0:y1, x0:x1] = np.random.randint(0, 4, (y1-y0, x1-x0), dtype=np.uint8)
        self._dirty = True

    def paint_circle(self, cx, cy, radius, tile):
        y0, y1 = max(cy - radius, 0), min(cy + radius + 1, self.h)
        x0, x1 = max(cx - radius, 0), min(cx + radius + 1, self.w)
        if y1 <= y0 or x1 <= x0: return
        ys, xs = np.arange(y0, y1)[:, None], np.arange(x0, x1)[None, :]
        mask = (xs - cx)**2 + (ys - cy)**2 <= radius * radius
        self.tiles[y0:y1, x0:x1] = np.where(mask, tile, self.tiles[y0:y1, x0:x1])
        nv = np.random.randint(0, 4, (y1-y0, x1-x0), dtype=np.uint8)
        self.variation[y0:y1, x0:x1] = np.where(mask, nv, self.variation[y0:y1, x0:x1])
        self._dirty = True

    def snapshot_region(self, cx, cy, radius):
        y0 = max(cy - radius - 1, 0); y1 = min(cy + radius + 2, self.h)
        x0 = max(cx - radius - 1, 0); x1 = min(cx + radius + 2, self.w)
        return (self.tiles[y0:y1, x0:x1].copy(), self.variation[y0:y1, x0:x1].copy(),
                x0, y0, x1, y1)

    def restore_region(self, td, vd, x0, y0, x1, y1):
        self.tiles[y0:y1, x0:x1] = td; self.variation[y0:y1, x0:x1] = vd
        self._dirty = True

    def save(self, path=SAVE_PATH):
        np.savez_compressed(path, tiles=self.tiles, variation=self.variation)
        print(f"[World] Saved to {path}")

    def load(self, path=SAVE_PATH):
        if not os.path.exists(path): return False
        d = np.load(path); self.tiles[:] = d["tiles"]; self.variation[:] = d["variation"]
        self._dirty = True; print(f"[World] Loaded from {path}"); return True

# ──────────────────────────────────────────────
# Camera
# ──────────────────────────────────────────────
class Camera:
    def __init__(self, sw, sh):
        self.sw, self.sh = sw, sh
        self.x = (WORLD_W * TILE_SIZE) / 2.0
        self.y = (WORLD_H * TILE_SIZE) / 2.0
        self.zoom = 1.0; self.target_zoom = 1.0
        self.min_zoom = 0.25; self.max_zoom = 4.0
        self.pan_speed = 600.0; self.lerp_factor = 0.15
        self._dragging = False
        self._drag_start_screen = (0.0, 0.0)
        self._drag_start_world = (0.0, 0.0)

    def update(self, dt, keys, mouse_pos):
        speed = self.pan_speed * dt / self.zoom
        dx = dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= speed
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:   dy += speed
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:   dx -= speed
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:  dx += speed
        self.x += dx; self.y += dy
        mx, my = mouse_pos; es = EDGE_SCROLL_SPEED * dt / self.zoom
        if mx < EDGE_SCROLL_ZONE:        self.x -= es * (1 - mx / EDGE_SCROLL_ZONE)
        elif mx > self.sw - EDGE_SCROLL_ZONE: self.x += es * (1 - (self.sw - mx) / EDGE_SCROLL_ZONE)
        if my < EDGE_SCROLL_ZONE:        self.y -= es * (1 - my / EDGE_SCROLL_ZONE)
        elif my > self.sh - EDGE_SCROLL_ZONE: self.y += es * (1 - (self.sh - my) / EDGE_SCROLL_ZONE)
        self.zoom += (self.target_zoom - self.zoom) * self.lerp_factor
        hw, hh = (self.sw/2)/self.zoom, (self.sh/2)/self.zoom
        self.x = max(hw, min(self.x, WORLD_W*TILE_SIZE - hw))
        self.y = max(hh, min(self.y, WORLD_H*TILE_SIZE - hh))

    def handle_scroll(self, d):
        f = 1.1 if d > 0 else 1/1.1
        self.target_zoom = max(self.min_zoom, min(self.target_zoom * f, self.max_zoom))

    def begin_drag(self, sp):
        self._dragging = True
        self._drag_start_screen = (float(sp[0]), float(sp[1]))
        self._drag_start_world = (self.x, self.y)

    def update_drag(self, sp):
        if not self._dragging: return
        self.x = self._drag_start_world[0] - (sp[0] - self._drag_start_screen[0]) / self.zoom
        self.y = self._drag_start_world[1] - (sp[1] - self._drag_start_screen[1]) / self.zoom

    def end_drag(self): self._dragging = False

    def world_to_screen(self, wx, wy):
        return (wx - self.x) * self.zoom + self.sw/2, (wy - self.y) * self.zoom + self.sh/2

    def screen_to_world(self, sx, sy):
        return (sx - self.sw/2) / self.zoom + self.x, (sy - self.sh/2) / self.zoom + self.y

    def screen_to_tile(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        return int(wx // TILE_SIZE), int(wy // TILE_SIZE)

    def visible_tile_range(self):
        wx0, wy0 = self.screen_to_world(0, 0)
        wx1, wy1 = self.screen_to_world(self.sw, self.sh)
        return (max(int(wx0//TILE_SIZE)-1, 0), max(int(wy0//TILE_SIZE)-1, 0),
                min(int(wx1//TILE_SIZE)+2, WORLD_W), min(int(wy1//TILE_SIZE)+2, WORLD_H))


# ──────────────────────────────────────────────
# Terrain Painter
# ──────────────────────────────────────────────
class TerrainPainter:
    MAX_UNDO = 50
    def __init__(self, world):
        self.world = world; self.tile_type = TileType.GRASS
        self.brush_size = 2; self.brush_shape = "circle"
        self._undo_stack = deque(maxlen=self.MAX_UNDO)
        self._stroke_snapshot = None; self._painting = False

    def begin_stroke(self, tx, ty):
        self._stroke_snapshot = self.world.snapshot_region(tx, ty, self.brush_size)
        self._painting = True; self._apply_brush(tx, ty)

    def continue_stroke(self, tx, ty):
        if self._painting: self._apply_brush(tx, ty)

    def end_stroke(self):
        if self._painting and self._stroke_snapshot:
            self._undo_stack.append(self._stroke_snapshot)
        self._painting = False; self._stroke_snapshot = None

    def undo(self):
        if self._undo_stack:
            td, vd, x0, y0, x1, y1 = self._undo_stack.pop()
            self.world.restore_region(td, vd, x0, y0, x1, y1)

    def _apply_brush(self, tx, ty):
        if self.brush_shape == "circle":
            self.world.paint_circle(tx, ty, self.brush_size, self.tile_type)
        else:
            self.world.paint_rect(tx, ty, self.brush_size, self.tile_type)


# ──────────────────────────────────────────────
# Renderer (tiles)
# ──────────────────────────────────────────────
def _build_color_lut():
    lut = {}; offsets = [(0,0,0),(-8,6,-4),(6,-6,4),(-4,-4,8)]
    for tt, (base, _) in TILE_PALETTE.items():
        for vi, (dr, dg, db) in enumerate(offsets):
            lut[(tt, vi)] = tuple(max(0,min(255,base[i]+o)) for i,o in enumerate((dr,dg,db)))
    return lut
COLOR_LUT = _build_color_lut()


class Renderer:
    def __init__(self, screen):
        self.screen = screen; self.show_grid = False
        self._tile_cache = {}; self._zoom_cache = {}; self._cached_zk = -1
        self._build_base_surfaces()

    def _build_base_surfaces(self):
        self._tile_cache.clear()
        for (tt, vi), color in COLOR_LUT.items():
            s = pygame.Surface((TILE_SIZE, TILE_SIZE)); s.fill(color)
            hl = tuple(min(255, c+22) for c in color)
            pygame.draw.line(s, hl, (0,0), (TILE_SIZE-1,0))
            pygame.draw.line(s, hl, (0,0), (0,TILE_SIZE-1))
            sh = tuple(max(0, c-18) for c in color)
            pygame.draw.line(s, sh, (TILE_SIZE-1,1), (TILE_SIZE-1,TILE_SIZE-1))
            pygame.draw.line(s, sh, (1,TILE_SIZE-1), (TILE_SIZE-1,TILE_SIZE-1))
            self._tile_cache[(tt, vi)] = s

    def _get_scaled(self, zts):
        k = round(zts * 10)
        if k == self._cached_zk and k in self._zoom_cache: return self._zoom_cache[k]
        sz = max(int(zts), 2)
        self._zoom_cache[k] = {key: pygame.transform.scale(v, (sz, sz)) for key, v in self._tile_cache.items()}
        self._cached_zk = k; return self._zoom_cache[k]

    def draw(self, world, camera, game_time):
        self.screen.fill((30, 30, 40))
        tx0, ty0, tx1, ty1 = camera.visible_tile_range()
        zts = TILE_SIZE * camera.zoom
        wp = math.sin(game_time * 2.5) * 12
        if zts >= 4:
            sc = self._get_scaled(zts); sz = max(int(zts), 2)
            for ty in range(ty0, ty1):
                rt, rv = world.tiles[ty, tx0:tx1], world.variation[ty, tx0:tx1]
                for i, tx in enumerate(range(tx0, tx1)):
                    tt, vi = int(rt[i]), int(rv[i])
                    sx, sy = camera.world_to_screen(tx*TILE_SIZE, ty*TILE_SIZE)
                    if tt == TileType.WATER:
                        w = int(wp + math.sin(game_time*3+tx*0.5+ty*0.3)*10)
                        bc = COLOR_LUT.get((tt,vi),(50,120,210))
                        wc = tuple(max(0,min(255,bc[j]+(w if j<2 else w//2))) for j in range(3))
                        pygame.draw.rect(self.screen, wc, (sx, sy, sz, sz))
                    else:
                        sf = sc.get((tt, vi))
                        if sf: self.screen.blit(sf, (sx, sy))
            if self.show_grid and zts >= 8: self._draw_grid(camera, tx0, ty0, tx1, ty1, zts)
        else:
            for ty in range(ty0, ty1):
                for tx in range(tx0, tx1):
                    sx, sy = camera.world_to_screen(tx*TILE_SIZE, ty*TILE_SIZE)
                    pygame.draw.rect(self.screen, TILE_PALETTE[world.get(tx,ty)][0],
                                     (sx, sy, max(int(zts),1), max(int(zts),1)))

    def _draw_grid(self, cam, tx0, ty0, tx1, ty1, zts):
        ov = pygame.Surface((cam.sw, cam.sh), pygame.SRCALPHA); gc = (0,0,0,40)
        for tx in range(tx0, tx1+1):
            sx, _ = cam.world_to_screen(tx*TILE_SIZE, 0); ix = int(sx)
            if 0<=ix<=cam.sw: pygame.draw.line(ov, gc, (ix,0), (ix, cam.sh))
        for ty in range(ty0, ty1+1):
            _, sy = cam.world_to_screen(0, ty*TILE_SIZE); iy = int(sy)
            if 0<=iy<=cam.sh: pygame.draw.line(ov, gc, (0,iy), (cam.sw, iy))
        self.screen.blit(ov, (0,0))

    def draw_brush_preview(self, camera, painter, mx, my):
        tx, ty = camera.screen_to_tile(mx, my); r = painter.brush_size; z = camera.zoom
        ov = pygame.Surface((camera.sw, camera.sh), pygame.SRCALPHA)
        bc = (*TILE_PALETTE[painter.tile_type][0], 90); brc = (255,255,255,140)
        for dy in range(-r, r+1):
            for dx in range(-r, r+1):
                if painter.brush_shape == "circle" and dx*dx+dy*dy > r*r: continue
                px, py = camera.world_to_screen((tx+dx)*TILE_SIZE, (ty+dy)*TILE_SIZE)
                s = int(z*TILE_SIZE)
                pygame.draw.rect(ov, bc, (px, py, s, s))
                pygame.draw.rect(ov, brc, (px, py, s, s), 1)
        self.screen.blit(ov, (0,0))


# ──────────────────────────────────────────────
# Minimap
# ──────────────────────────────────────────────
class Minimap:
    def __init__(self):
        self.w, self.h = MINIMAP_W, MINIMAP_H
        self.surface = pygame.Surface((self.w, self.h))
        self._last_hash = None

    def update(self, world, entities):
        ch = hash(world.tiles.tobytes())
        if not world._dirty and ch == self._last_hash:
            self._draw_dots(entities); return
        self._last_hash = ch; world._dirty = False
        sx, sy = world.w/self.w, world.h/self.h
        yi = (np.arange(self.h)*sy).astype(int).clip(0,world.h-1)
        xi = (np.arange(self.w)*sx).astype(int).clip(0,world.w-1)
        s = world.tiles[np.ix_(yi, xi)]
        rgb = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        for tt, (base, _) in TILE_PALETTE.items():
            rgb[s == tt] = base
        pygame.surfarray.blit_array(self.surface, rgb.transpose(1, 0, 2))
        self._draw_dots(entities)

    def _draw_dots(self, entities):
        from villager import Villager, STATE_COLORS
        from enemy import Enemy
        for b in entities.buildings():
            bx, by = int((b.origin_tx/WORLD_W)*self.w), int((b.origin_ty/WORLD_H)*self.h)
            c = (255,255,255) if b.built else (120,120,80)
            if b.btype == BuildingType.WALL:
                c = (160, 160, 165) if b.built else (100,100,100)
            pygame.draw.rect(self.surface, c, (bx-1, by-1, 4, 4))
        for e in entities.all():
            if not e.alive: continue
            if isinstance(e, Building): continue
            if isinstance(e, Enemy):
                dx = int((e.x/(WORLD_W*TILE_SIZE))*self.w)
                dy = int((e.y/(WORLD_H*TILE_SIZE))*self.h)
                self.surface.set_at((max(0,min(dx,self.w-1)), max(0,min(dy,self.h-1))), (255,60,60))
                continue
            v = e; dx = int((v.x/(WORLD_W*TILE_SIZE))*self.w); dy = int((v.y/(WORLD_H*TILE_SIZE))*self.h)
            c = STATE_COLORS.get(v.fsm.current_state if v.fsm else "idle", (150,150,150))
            if v.selected: c = (255,255,255)
            self.surface.set_at((max(0,min(dx,self.w-1)), max(0,min(dy,self.h-1))), c)

    def _draw_diplomacy_dots(self, sim):
        """Draw AI village markers on the minimap."""
        if not sim.diplomacy._discovered:
            return
        from diplomacy import relation_color
        for v in sim.diplomacy.villages:
            dx = int((v.map_tx / WORLD_W) * self.w)
            dy = int((v.map_ty / WORLD_H) * self.h)
            dx = max(0, min(dx, self.w - 1))
            dy = max(0, min(dy, self.h - 1))
            c = relation_color(v.relation)
            if v.at_war:
                c = (255, 50, 50)
            # Draw a diamond shape for AI villages
            for ox, oy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                px, py = dx + ox, dy + oy
                if 0 <= px < self.w and 0 <= py < self.h:
                    self.surface.set_at((px, py), c)

    def draw(self, screen, camera, sim=None):
        mx = screen.get_width() - self.w - MINIMAP_MARGIN; my = MINIMAP_MARGIN
        pygame.draw.rect(screen, (200,200,200), (mx-2,my-2,self.w+4,self.h+4), 2, border_radius=3)
        screen.blit(self.surface, (mx, my))
        wpw, wph = WORLD_W*TILE_SIZE, WORLD_H*TILE_SIZE
        vx0 = camera.x - (camera.sw/2)/camera.zoom; vy0 = camera.y - (camera.sh/2)/camera.zoom
        vw, vh = camera.sw/camera.zoom, camera.sh/camera.zoom
        rx = max(mx, min(int(vx0/wpw*self.w)+mx, mx+self.w))
        ry = max(my, min(int(vy0/wph*self.h)+my, my+self.h))
        rw = min(int(vw/wpw*self.w), mx+self.w-rx); rh = min(int(vh/wph*self.h), my+self.h-ry)
        pygame.draw.rect(screen, (255,255,0), (rx,ry,rw,rh), 1)

    def handle_click(self, sw, cp, camera):
        mx = sw - self.w - MINIMAP_MARGIN; my = MINIMAP_MARGIN
        if not pygame.Rect(mx, my, self.w, self.h).collidepoint(cp): return False
        camera.x = ((cp[0]-mx)/self.w)*WORLD_W*TILE_SIZE
        camera.y = ((cp[1]-my)/self.h)*WORLD_H*TILE_SIZE
        return True


# ──────────────────────────────────────────────
# HUD
# ──────────────────────────────────────────────
class HUD:
    def __init__(self):
        self.font = pygame.font.SysFont("consolas", 16)
        self.font_sm = pygame.font.SysFont("consolas", 14)
        self.font_ev = pygame.font.SysFont("consolas", 13)
        self._bs = 40  # button size

    def draw(self, screen, painter, camera, fps, cursor_tile,
             show_grid, game_time, sim, build_mode):
        # ── palette bar ──
        x, y = 10, 10; sel = painter.tile_type
        for i, (tt, (base, name)) in enumerate(TILE_PALETTE.items()):
            r = pygame.Rect(x + i*(self._bs+4), y, self._bs, self._bs)
            pygame.draw.rect(screen, base, r, border_radius=4)
            bc = (255,255,0) if tt == sel and not build_mode else (180,180,180)
            bw = 3 if tt == sel and not build_mode else 1
            pygame.draw.rect(screen, bc, r, bw, border_radius=4)
            screen.blit(self.font.render(str(i+1), True, (255,255,255)), (r.x+14, r.y+12))

        # ── building buttons ──
        bx = x + 6 * (self._bs + 4) + 16
        for idx, bt in enumerate(BUILD_BAR_ORDER):
            d = BUILDING_DEFS[bt]
            r = pygame.Rect(bx + idx*(self._bs+4), y, self._bs, self._bs)
            pygame.draw.rect(screen, d["color"], r, border_radius=4)
            bc2 = (255,255,0) if build_mode == bt else (180,180,180)
            bw2 = 3 if build_mode == bt else 1
            pygame.draw.rect(screen, bc2, r, bw2, border_radius=4)
            # Key hint
            if idx < 3:
                key_label = str(7 + idx)
            elif idx == 3:
                key_label = "0"
            elif idx == 4:
                key_label = "-"
            else:
                key_label = ""  # Click only for Library/TradingPost/Embassy
            screen.blit(self.font.render(key_label, True, (255,255,255)), (r.x+14, r.y+2))
            # Cost label
            cost_str = "/".join(f"{v}{k[0]}" for k,v in d["cost"].items()) or "-"
            screen.blit(self.font_sm.render(cost_str, True, (220,220,220)), (r.x+2, r.y+24))

        # ── cursor tile ──
        tx, ty = cursor_tile
        if 0 <= tx < WORLD_W and 0 <= ty < WORLD_H:
            screen.blit(self.font.render(f"Tile ({tx}, {ty})", True, (220,220,220)), (10, 60))

        # ── selected villager panel ──
        sel_v = self._get_sel_villager(sim)
        if sel_v:
            v = sel_v; st = v.fsm.current_state if v.fsm else "?"
            sl = STATE_LABELS.get(st, st)
            guard_tag = " [GUARD]" if v.is_guard else ""
            role_name = ROLE_NAMES.get(v.role, "?")
            lines = [f"{v.name}{guard_tag}  |  {sl}  |  {role_name}",
                     f"HP:{v.hp}/{v.max_hp}  Energy:{v.energy:.0f}/{v.max_energy:.0f}  Hunger:{v.hunger:.0f}/{v.max_hunger:.0f}",
                     f"Carry: {v.carry_count()}/{v.max_carry}  Dmg:{v.damage}"]
            for i, l in enumerate(lines):
                screen.blit(self.font.render(l, True, (255,255,200)), (10, 82+i*20))

        # ── bottom info ──
        iy = screen.get_height() - 70
        pop = sim.population; cap = sim.entities.pop_cap()
        wood = sim.global_resources.get("wood", 0)
        food = sim.global_resources.get("food", 0)
        stone = sim.global_resources.get("stone", 0)
        iron = sim.global_resources.get("iron", 0)
        zp = int(camera.zoom * 100)
        phase = sim.day_phase
        day = sim.day_number
        weather_label = sim.weather.label
        ptag = "  ** PAUSED **" if sim.paused else ""
        raid_tag = "  !! RAID !! " if sim._raid_active else ""

        # Research progress indicator
        res_tag = ""
        if sim.research.current_research is not None:
            td = TECH_DEFS[sim.research.current_research]
            pct = int(sim.research.progress_fraction * 100)
            res_tag = f"  Res:{td['name']} {pct}%"

        # Merchant indicator
        merch_tag = "  [Merchant]" if sim.trading.merchant_present else ""

        # Diplomacy indicator
        diplo_tag = ""
        if sim.diplomacy._discovered:
            dm = sim.diplomacy
            parts = []
            if dm.ally_count > 0:
                parts.append(f"Allies:{dm.ally_count}")
            if dm.war_count > 0:
                parts.append(f"Wars:{dm.war_count}")
            if dm.pact_count > 0:
                parts.append(f"Pacts:{dm.pact_count}")
            if parts:
                diplo_tag = "  " + " ".join(parts)

        p1 = [f"FPS:{fps:.0f}", f"Zoom:{zp}%", f"Pop:{pop}/{cap}",
              f"W:{wood}", f"F:{food}", f"S:{stone}", f"I:{iron}",
              f"Day {day} {phase}", f"Weather:{weather_label}",
              f"Guards:{sim.guard_count} Enemies:{sim.enemy_count}{ptag}{raid_tag}{res_tag}{merch_tag}{diplo_tag}"]
        screen.blit(self.font.render("  |  ".join(p1), True, (200,200,200)), (10, iy))
        hints = ("[/]Size B Shape X Grid G Gen F5/F9 Save/Load V Spawn "
                 "0-9/- Build H TownHall Space Pause Ctrl+Z Undo "
                 "G(guard) N(raid) T(Tech) R(Role) C/Q/E(Trade) "
                 "U(Upgrade) P(Stats) M(Sound) Esc")
        screen.blit(self.font_sm.render(hints, True, (140,140,140)), (10, iy+20))

        # ── weather indicator (top-right area) ──
        self._draw_weather_badge(screen, sim, screen.get_width() - MINIMAP_W - MINIMAP_MARGIN - 120, 10)

        # ── event log (bottom-right) ──
        self._draw_event_log(screen, sim, bx + len(BUILD_BAR_ORDER)*(self._bs+4) + 20, 10)

    def _draw_weather_badge(self, screen, sim, x, y):
        weather = sim.weather.current
        icons = {
            Weather.CLEAR: ("Sun", (255, 220, 80)),
            Weather.RAIN:  ("Rain", (120, 160, 255)),
            Weather.STORM: ("Storm", (200, 120, 255)),
            Weather.SNOW:  ("Snow", (220, 230, 255)),
        }
        label, color = icons.get(weather, ("?", (200,200,200)))
        text = f"{label}  Mv:{sim.weather.move_mult:.1f}x Farm:{sim.weather.farm_mult:.1f}x"
        bg = pygame.Surface((250, 22), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 80))
        screen.blit(bg, (x - 4, y - 2))
        screen.blit(self.font.render(text, True, color), (x, y))

    def _draw_event_log(self, screen, sim, x, y):
        entries = sim.event_log.entries
        if not entries: return
        max_lines = 12
        visible = list(entries)[-max_lines:]
        lh = 16
        h = len(visible) * lh + 8
        w = 360
        ry = screen.get_height() - 70 - h - 5
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 100))
        screen.blit(ov, (x, ry))
        for i, (text, color) in enumerate(visible):
            age_factor = (i + 1) / len(visible)
            fc = tuple(int(c * (0.5 + 0.5 * age_factor)) for c in color)
            s = self.font_ev.render(text, True, fc)
            screen.blit(s, (x + 6, ry + 4 + i * lh))

    @staticmethod
    def _get_sel_villager(sim):
        from villager import Villager
        for e in sim.entities.all():
            if isinstance(e, Villager) and e.selected and e.alive: return e
        return None


# ════════════════════════════════════════════════
#  Tech Tree Panel
# ════════════════════════════════════════════════

# Layout positions for each tech in the tree (col, row) for visual arrangement
_TECH_LAYOUT = {
    Tech.BETTER_TOOLS:   (0, 0),
    Tech.AGRICULTURE:    (0, 2),
    Tech.FORTIFICATIONS: (1, 0),
    Tech.MEDICINE:       (1, 1),
    Tech.METALLURGY:     (1, 2),
    Tech.ARCHERY:        (2, 1),
    Tech.STORAGE_MASTER: (2, 0),
    Tech.TRADE_ROUTES:   (2, 2),
}

# Ordered list for key binding 1-8
_TECH_KEY_ORDER = list(Tech)


def draw_tech_tree(screen, sim, font, font_sm, font_ev):
    """Draw the technology tree overlay panel. Returns nothing."""
    sw, sh = screen.get_size()

    # Panel dimensions
    panel_w, panel_h = 620, 420
    px = (sw - panel_w) // 2
    py = (sh - panel_h) // 2

    # Semi-transparent background
    bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    bg.fill((20, 20, 35, 220))
    screen.blit(bg, (px, py))
    pygame.draw.rect(screen, (120, 100, 60), (px, py, panel_w, panel_h), 2, border_radius=6)

    # Title
    title = font.render("TECHNOLOGY TREE", True, (255, 220, 100))
    screen.blit(title, (px + panel_w // 2 - title.get_width() // 2, py + 8))

    # Library status
    has_lib = sim.research.has_library(sim)
    lib_color = (100, 255, 100) if has_lib else (255, 100, 100)
    lib_text = "Library: Built" if has_lib else "Library: NOT BUILT"
    screen.blit(font_sm.render(lib_text, True, lib_color), (px + 10, py + 32))

    # Current research progress
    if sim.research.current_research is not None:
        td = TECH_DEFS[sim.research.current_research]
        pct = sim.research.progress_fraction
        prog_text = f"Researching: {td['name']} ({int(pct * 100)}%)"
        screen.blit(font_sm.render(prog_text, True, (180, 200, 255)), (px + 200, py + 32))
        # Progress bar
        bar_x, bar_y = px + 200, py + 48
        bar_w, bar_h = 200, 10
        pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
        pygame.draw.rect(screen, (80, 140, 255), (bar_x, bar_y, int(bar_w * pct), bar_h))
        pygame.draw.rect(screen, (100, 100, 120), (bar_x, bar_y, bar_w, bar_h), 1)

    # Grid layout
    cell_w, cell_h = 145, 90
    margin_left = px + 40
    margin_top = py + 70

    # Draw prerequisite lines first (behind nodes)
    for tech, defn in TECH_DEFS.items():
        for req in defn["requires"]:
            if tech in _TECH_LAYOUT and req in _TECH_LAYOUT:
                cx1 = margin_left + _TECH_LAYOUT[req][0] * (cell_w + 20) + cell_w // 2
                cy1 = margin_top + _TECH_LAYOUT[req][1] * (cell_h + 15) + cell_h
                cx2 = margin_left + _TECH_LAYOUT[tech][0] * (cell_w + 20) + cell_w // 2
                cy2 = margin_top + _TECH_LAYOUT[tech][1] * (cell_h + 15)
                # Line color: green if both researched, yellow if one, gray otherwise
                both_done = sim.research.is_researched(req) and sim.research.is_researched(tech)
                one_done = sim.research.is_researched(req) or sim.research.is_researched(tech)
                lc = (100, 255, 100) if both_done else ((255, 220, 100) if one_done else (80, 80, 100))
                pygame.draw.line(screen, lc, (cx1, cy1), (cx2, cy2), 2)

    # Draw each tech node
    for idx, tech in enumerate(_TECH_KEY_ORDER):
        defn = TECH_DEFS[tech]
        col, row = _TECH_LAYOUT[tech]
        nx = margin_left + col * (cell_w + 20)
        ny = margin_top + row * (cell_h + 15)

        researched = sim.research.is_researched(tech)
        in_progress = sim.research.current_research == tech
        available = sim.research.can_research(tech) and has_lib

        # Node background
        if researched:
            node_bg = (40, 80, 40, 200)
            border_col = (100, 255, 100)
        elif in_progress:
            node_bg = (40, 50, 80, 200)
            border_col = (80, 140, 255)
        elif available:
            node_bg = (60, 60, 40, 200)
            border_col = (220, 200, 80)
        else:
            node_bg = (40, 40, 40, 180)
            border_col = (80, 80, 80)

        node_surf = pygame.Surface((cell_w, cell_h), pygame.SRCALPHA)
        node_surf.fill(node_bg)
        screen.blit(node_surf, (nx, ny))
        pygame.draw.rect(screen, border_col, (nx, ny, cell_w, cell_h), 2, border_radius=4)

        # Key hint
        key_text = f"[{idx + 1}]"
        key_color = (255, 255, 255) if (available or in_progress) else (100, 100, 100)
        screen.blit(font_ev.render(key_text, True, key_color), (nx + 3, ny + 2))

        # Tech name
        name_color = (220, 255, 220) if researched else ((180, 200, 255) if in_progress else (200, 200, 200))
        screen.blit(font_sm.render(defn["name"], True, name_color), (nx + 5, ny + 18))

        # Description
        screen.blit(font_ev.render(defn["desc"], True, (170, 170, 170)), (nx + 5, ny + 35))

        # Cost
        cost_str = " ".join(f"{v}{k[0]}" for k, v in defn["cost"].items())
        screen.blit(font_ev.render(cost_str, True, (180, 160, 100)), (nx + 5, ny + 50))

        # Status indicator
        if researched:
            screen.blit(font_sm.render("DONE", True, (100, 255, 100)), (nx + cell_w - 42, ny + 2))
        elif in_progress:
            pct = int(sim.research.progress_fraction * 100)
            screen.blit(font_ev.render(f"{pct}%", True, (80, 140, 255)), (nx + cell_w - 30, ny + 4))
        elif not has_lib:
            screen.blit(font_ev.render("No Lib", True, (255, 100, 100)), (nx + cell_w - 42, ny + 4))
        elif defn["requires"] and not all(sim.research.is_researched(r) for r in defn["requires"]):
            screen.blit(font_ev.render("Locked", True, (180, 100, 100)), (nx + cell_w - 42, ny + 4))

    # Bottom hint
    hint = "Press 1-8 to start research  |  T to close  |  X to cancel current"
    screen.blit(font_ev.render(hint, True, (140, 140, 160)),
                (px + panel_w // 2 - font_ev.size(hint)[0] // 2, py + panel_h - 20))


# ════════════════════════════════════════════════
#  Trade Offers Panel
# ════════════════════════════════════════════════

def draw_trade_panel(screen, sim, font, font_sm, font_ev):
    """Draw trade offers when a merchant is present."""
    if not sim.trading.merchant_present:
        return
    if not sim.trading.offers:
        return

    sw, sh = screen.get_size()
    panel_w, panel_h = 340, 30 + len(sim.trading.offers) * 50
    px = (sw - panel_w) // 2
    py = 10

    bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    bg.fill((30, 25, 10, 210))
    screen.blit(bg, (px, py))
    pygame.draw.rect(screen, (220, 180, 60), (px, py, panel_w, panel_h), 2, border_radius=5)

    # Title
    title = font_sm.render("MERCHANT CARAVAN", True, (255, 220, 100))
    screen.blit(title, (px + panel_w // 2 - title.get_width() // 2, py + 5))

    # Timer
    timer_text = f"Leaves in {sim.trading._merchant_timer} ticks"
    screen.blit(font_ev.render(timer_text, True, (180, 160, 100)), (px + 10, py + 5))

    trade_keys = ["C", "Q", "E"]

    for i, offer in enumerate(sim.trading.offers):
        oy = py + 25 + i * 50
        # Offer text
        give_ok = sim.global_resources.get(offer.give_res, 0) >= offer.give_amt
        text_color = (220, 220, 200) if give_ok else (150, 100, 100)

        offer_text = f"[{trade_keys[i]}]  {offer.give_amt} {offer.give_res}  ->  {offer.recv_amt} {offer.recv_res}"
        screen.blit(font_sm.render(offer_text, True, text_color), (px + 10, oy))

        # affordability hint
        if not give_ok:
            have = sim.global_resources.get(offer.give_res, 0)
            hint = f"(need {offer.give_amt}, have {have})"
            screen.blit(font_ev.render(hint, True, (200, 80, 80)), (px + 10, oy + 18))
        else:
            screen.blit(font_ev.render("ACCEPT", True, (100, 220, 100)), (px + 10, oy + 18))

    # Hint at bottom
    hint = "Press C/Q/E to accept  |  Merchant auto-departs"
    screen.blit(font_ev.render(hint, True, (140, 140, 120)),
                (px + panel_w // 2 - font_ev.size(hint)[0] // 2, py + panel_h - 18))


# ════════════════════════════════════════════════
#  Build-mode placement preview
# ════════════════════════════════════════════════
def draw_build_preview(screen, camera, build_mode, mx, my, world, entities):
    if build_mode is None:
        return
    d = BUILDING_DEFS[build_mode]
    w, h = d["w"], d["h"]
    tx, ty = camera.screen_to_tile(mx, my)
    valid = True
    for dy in range(h):
        for dx in range(w):
            cx, cy = tx + dx, ty + dy
            if not world.in_bounds(cx, cy) or world.get(cx, cy) != TileType.GRASS:
                valid = False; break

    # Also check not overlapping other buildings
    if valid:
        for b in entities.buildings():
            if not b.alive: continue
            tx0, ty0, tx1, ty1 = b.tile_rect
            ox0, oy0 = max(tx, tx0), max(ty, ty0)
            ox1, oy1 = min(tx + w, tx1), min(ty + h, ty1)
            if ox0 < ox1 and oy0 < oy1:
                valid = False; break

    sx, sy = camera.world_to_screen(tx * TILE_SIZE, ty * TILE_SIZE)
    bw = w * TILE_SIZE * camera.zoom
    bh = h * TILE_SIZE * camera.zoom
    ov = pygame.Surface((int(bw), int(bh)), pygame.SRCALPHA)
    col = (0, 255, 0, 80) if valid else (255, 0, 0, 80)
    ov.fill(col)
    border = (0, 255, 0) if valid else (255, 0, 0)
    screen.blit(ov, (sx, sy))
    pygame.draw.rect(screen, border, (sx, sy, int(bw), int(bh)), 2)
    lbl = f"{d['name']} ({w}x{h})"
    if d["cost"]:
        lbl += " " + " ".join(f"{v}{k[0]}" for k,v in d["cost"].items())
    font = pygame.font.SysFont("consolas", 16)
    ls = font.render(lbl, True, border)
    screen.blit(ls, (sx, sy - 20))


# ════════════════════════════════════════════════
#  Day/night overlay
# ════════════════════════════════════════════════
_night_overlay = None
_night_last_size = (0, 0)
_night_last_key = -1

def draw_night_overlay(screen, sim):
    global _night_overlay, _night_last_size, _night_last_key
    r, g, b, a = get_night_tint(sim.sim_time)
    if a <= 0:
        return
    key = (r, g, b, a)
    sw, sh = screen.get_size()
    if key != _night_last_key or (sw, sh) != _night_last_size:
        _night_overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        _night_overlay.fill((r, g, b, a))
        _night_last_key = key
        _night_last_size = (sw, sh)
    screen.blit(_night_overlay, (0, 0))


# ════════════════════════════════════════════════
#  Phase 6: Achievement popup
# ════════════════════════════════════════════════
def draw_achievement_popup(screen, sim, font, font_sm):
    """Draw a slide-in achievement notification at the top-center."""
    am = sim.achievements
    aid = am.popup_achievement
    if not aid or am.popup_alpha <= 0:
        return
    defn = ACHIEVEMENT_DEFS.get(aid)
    if not defn:
        return

    sw = screen.get_width()
    pw, ph = 380, 60
    px = (sw - pw) // 2
    # Slide in from top
    py = -ph + int((ph + 10) * min(1.0, (180 - am._popup[1]) / 15.0))
    py = max(5, py)

    alpha = am.popup_alpha
    bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
    bg.fill((20, 20, 35, int(alpha * 0.85)))
    screen.blit(bg, (px, py))
    pygame.draw.rect(screen, (*defn["color"], alpha), (px, py, pw, ph), 2, border_radius=8)

    # Star icon
    star = font.render("\u2605", True, (*defn["color"][:3],))
    screen.blit(star, (px + 8, py + 6))

    # Text
    title = font.render("ACHIEVEMENT UNLOCKED", True, (255, 255, 255))
    title.set_alpha(alpha)
    screen.blit(title, (px + 30, py + 6))

    desc = font_sm.render(f"{defn['name']} — {defn['desc']}", True, defn["color"])
    desc.set_alpha(alpha)
    screen.blit(desc, (px + 30, py + 30))


# ════════════════════════════════════════════════
#  Phase 6: Statistics panel (P key)
# ════════════════════════════════════════════════
def draw_stats_panel(screen, sim, font, font_sm, font_ev):
    """Draw a comprehensive statistics overlay."""
    sw, sh = screen.get_size()
    pw, ph = 400, 450
    px = (sw - pw) // 2
    py = (sh - ph) // 2

    bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
    bg.fill((15, 15, 25, 230))
    screen.blit(bg, (px, py))
    pygame.draw.rect(screen, (100, 120, 160), (px, py, pw, ph), 2, border_radius=6)

    title = font.render("VILLAGE STATISTICS", True, (255, 220, 100))
    screen.blit(title, (px + pw // 2 - title.get_width() // 2, py + 8))

    s = sim.stats
    y = py + 35
    lh = 20

    sections = [
        ("Population", [
            (f"Current Population: {sim.population}", (200, 200, 200)),
            (f"Population Cap: {sim.entities.pop_cap()}", (200, 200, 200)),
            (f"Guards: {sim.guard_count}", (80, 140, 255)),
            (f"Villagers Lost: {s.get('villagers_lost', 0)}", (255, 120, 120)),
        ]),
        ("Resources (total gathered)", [
            (f"Wood Gathered: {s.get('wood_gathered', 0)}", (220, 180, 100)),
            (f"Stone Mined: {s.get('stone_mined', 0)}", (180, 170, 150)),
            (f"Iron Mined: {s.get('iron_mined', 0)}", (200, 200, 220)),
            (f"Food Produced: {s.get('food_produced', 0)}", (100, 220, 100)),
            (f"Current — Wood:{sim.global_resources.get('wood',0)} "
             f"Food:{sim.global_resources.get('food',0)} "
             f"Stone:{sim.global_resources.get('stone',0)} "
             f"Iron:{sim.global_resources.get('iron',0)}", (180, 180, 180)),
        ]),
        ("Combat", [
            (f"Enemies Killed: {s.get('enemies_killed', 0)}", (255, 100, 100)),
            (f"Raids Survived: {s.get('raids_survived', 0)}", (200, 150, 255)),
            (f"Buildings Destroyed: {s.get('buildings_destroyed', 0)}", (255, 150, 100)),
            (f"Trades Completed: {s.get('trades_completed', 0)}", (220, 200, 100)),
        ]),
        ("Buildings & Tech", [
            (f"Buildings Completed: {s.get('buildings_completed', 0)}", (200, 200, 100)),
            (f"Buildings Upgraded: {s.get('buildings_upgraded', 0)}", (100, 255, 200)),
            (f"Techs Researched: {len(sim.research.researched)}/8", (100, 200, 255)),
            (f"Achievements: {len(sim.achievements.unlocked)}/"
             f"{len(ACHIEVEMENT_ORDER)}", (255, 220, 100)),
        ]),
        ("Diplomacy", [
            (f"Villages Discovered: {len(sim.diplomacy.villages)}", (100, 180, 255)),
            (f"Allies: {sim.diplomacy.ally_count}  "
             f"Pacts: {sim.diplomacy.pact_count}  "
             f"Wars: {sim.diplomacy.war_count}", (200, 200, 200)),
            (f"Gifts Sent: {s.get('gifts_sent', 0)}  "
             f"Tribute: {s.get('tribute_received', 0)}", (180, 180, 180)),
            (f"Reinforcements: {s.get('reinforcements_received', 0)}", (80, 200, 255)),
        ]),
        ("Time", [
            (f"Day: {sim.day_number}  Phase: {sim.day_phase}", (220, 200, 180)),
            (f"Total Ticks: {sim.total_ticks}", (160, 160, 160)),
            (f"Current Weather: {sim.weather.label}", (180, 200, 220)),
        ]),
    ]

    for section_name, lines in sections:
        # Section header
        hdr = font_sm.render(f"── {section_name} ──", True, (120, 140, 180))
        screen.blit(hdr, (px + 10, y))
        y += lh
        for text, color in lines:
            screen.blit(font_ev.render(text, True, color), (px + 20, y))
            y += lh - 2
        y += 6

    hint = "Press P to close"
    h = font_ev.render(hint, True, (140, 140, 160))
    screen.blit(h, (px + pw // 2 - h.get_width() // 2, py + ph - 22))


# ════════════════════════════════════════════════
#  Phase 6: Game Over / Victory overlay
# ════════════════════════════════════════════════
def draw_game_over(screen, sim, font, font_sm, font_ev):
    """Draw the game over or victory screen."""
    sw, sh = screen.get_size()

    # Dark overlay
    ov = pygame.Surface((sw, sh), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 160))
    screen.blit(ov, (0, 0))

    pw, ph = 500, 300
    px = (sw - pw) // 2
    py = (sh - ph) // 2

    bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
    if sim.victory:
        bg.fill((20, 30, 20, 230))
    else:
        bg.fill((30, 15, 15, 230))
    screen.blit(bg, (px, py))

    border_col = (255, 215, 0) if sim.victory else (200, 50, 50)
    pygame.draw.rect(screen, border_col, (px, py, pw, ph), 3, border_radius=8)

    # Title
    if sim.victory:
        title_text = "VICTORY!"
        title_color = (255, 215, 0)
        sub = "Your village has become a thriving civilization!"
    else:
        title_text = "DEFEAT"
        title_color = (255, 60, 60)
        sub = sim.game_over_reason

    title = font.render(title_text, True, title_color)
    screen.blit(title, (px + pw // 2 - title.get_width() // 2, py + 30))

    sub_surf = font_sm.render(sub, True, (200, 200, 200))
    screen.blit(sub_surf, (px + pw // 2 - sub_surf.get_width() // 2, py + 65))

    # Stats summary
    s = sim.stats
    y = py + 100
    summary = [
        f"Days Survived: {sim.day_number}",
        f"Enemies Killed: {s.get('enemies_killed', 0)}",
        f"Raids Survived: {s.get('raids_survived', 0)}",
        f"Techs Researched: {len(sim.research.researched)}/8",
        f"Achievements: {len(sim.achievements.unlocked)}/{len(ACHIEVEMENT_ORDER)}",
        f"Peak Population: {sim.population}",
    ]
    for line in summary:
        screen.blit(font_ev.render(line, True, (180, 180, 180)), (px + 40, y))
        y += 22

    # Restart hint
    hint = font.render("Press BACKSPACE to restart", True, (220, 220, 100))
    screen.blit(hint, (px + pw // 2 - hint.get_width() // 2, py + ph - 45))


# ════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    pygame.display.set_caption("God Simulator — Phase 7")
    clock = pygame.time.Clock()

    world = World(WORLD_W, WORLD_H)
    entities = EntityManager()
    camera = Camera(SCREEN_W, SCREEN_H)
    painter = TerrainPainter(world)
    renderer = Renderer(screen)
    minimap = Minimap()
    hud = HUD()
    sim = SimulationManager(world, entities, SCREEN_W, SCREEN_H)

    build_mode: Optional[BuildingType] = None
    game_time = 0.0
    running = True

    # Phase 5: tech tree panel toggle
    show_tech_tree: bool = False

    # Phase 6: stats panel toggle
    show_stats: bool = False

    # Phase 7: diplomacy panel toggle & selected village
    show_diplomacy: bool = False
    diplo_selected: int = 0  # Index of selected village in diplomacy panel

    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        fps = clock.get_fps()
        game_time += dt
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                camera.sw, camera.sh = event.w, event.h
                renderer.screen = screen; renderer._zoom_cache.clear(); renderer._cached_zk = -1
                sim.weather.resize(event.w, event.h)

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if show_tech_tree:
                        show_tech_tree = False
                    elif show_stats:
                        show_stats = False
                    elif show_diplomacy:
                        show_diplomacy = False
                    elif build_mode is not None:
                        build_mode = None
                    else:
                        running = False

                # ── Phase 7: Diplomacy panel (D) ──
                elif event.key == pygame.K_d:
                    if not show_tech_tree and not show_stats:
                        show_diplomacy = not show_diplomacy

                # ── Phase 7: Diplomacy actions (only when panel is open) ──
                elif show_diplomacy:
                    dm = sim.diplomacy
                    # Village selection: 1-4
                    if event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                        idx = event.key - pygame.K_1
                        if dm._discovered and idx < len(dm.villages):
                            diplo_selected = idx
                    # Gift (G)
                    elif event.key == pygame.K_g:
                        msg = dm.send_gift(diplo_selected, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                            sim.sounds.play("error")
                    # Trade pact (T)
                    elif event.key == pygame.K_t:
                        msg = dm.propose_trade_pact(diplo_selected, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                            sim.sounds.play("error")
                    # Alliance (A)
                    elif event.key == pygame.K_a:
                        msg = dm.propose_alliance(diplo_selected, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                            sim.sounds.play("error")
                    # War (W)
                    elif event.key == pygame.K_w:
                        msg = dm.declare_war(diplo_selected, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                            sim.sounds.play("error")
                    # Peace (K)
                    elif event.key == pygame.K_k:
                        msg = dm.propose_peace(diplo_selected, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                            sim.sounds.play("error")
                    # Accept proposal (J)
                    elif event.key == pygame.K_j:
                        msg = dm.respond_to_proposal(diplo_selected, True, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                    # Reject proposal (F)
                    elif event.key == pygame.K_f:
                        msg = dm.respond_to_proposal(diplo_selected, False, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))

                # ── Phase 6: Backspace to restart after game over ──
                elif event.key == pygame.K_BACKSPACE:
                    if sim.game_over or sim.victory:
                        # Restart
                        world = World(WORLD_W, WORLD_H)
                        entities = EntityManager()
                        sim = SimulationManager(world, entities, SCREEN_W, SCREEN_H)
                        sim.game_over = False
                        sim.victory = False
                        sim.game_over_reason = ""
                        show_tech_tree = False
                        show_stats = False
                        show_diplomacy = False
                        diplo_selected = 0
                        build_mode = None
                        continue

                # ── Phase 6: Stats panel (P) ──
                elif event.key == pygame.K_p:
                    if not show_tech_tree and not show_diplomacy:
                        show_stats = not show_stats

                # ── Phase 6: Sound toggle (M) ──
                elif event.key == pygame.K_m:
                    enabled = sim.sounds.toggle()
                    sim.event_log.add(
                        f"Sound {'ON' if enabled else 'OFF'}",
                        (180, 180, 180),
                    )

                # ── Phase 6: Upgrade building (U) ──
                elif event.key == pygame.K_u:
                    if not show_tech_tree and not show_stats and not show_diplomacy:
                        # Check if a building is selected
                        sel_b = None
                        for e in sim.entities.all():
                            if isinstance(e, Building) and e.selected and e.built and e.alive:
                                sel_b = e
                                break
                        if sel_b is None:
                            # Try clicking on tile with building
                            tx, ty = camera.screen_to_tile(*mouse_pos)
                            for b in sim.entities.buildings():
                                tx0, ty0, tx1, ty1 = b.tile_rect
                                if tx0 <= tx < tx1 and ty0 <= ty < ty1 and b.built and b.alive:
                                    sel_b = b
                                    break
                        if sel_b:
                            if sel_b.btype not in UPGRADEABLE:
                                sim.event_log.add(f"{sel_b.display_name} cannot be upgraded.", (255, 100, 100))
                                sim.sounds.play("error")
                            elif sel_b.level >= 3:
                                sim.event_log.add(f"{sel_b.display_name} is already max level!", (255, 200, 100))
                                sim.sounds.play("error")
                            elif sel_b.upgrading:
                                sim.event_log.add(f"{sel_b.display_name} is already upgrading.", (255, 200, 100))
                            else:
                                msg = start_upgrade(sel_b, sim)
                                if msg:
                                    sim.event_log.add(msg, (255, 100, 100))
                                    sim.sounds.play("error")
                                else:
                                    sim.sounds.play("place")

                # ── Phase 5: Tech tree toggle (T) ──
                elif event.key == pygame.K_t:
                    if not show_diplomacy:
                        show_tech_tree = not show_tech_tree

                # ── Phase 5: Role cycling (R) ──
                elif event.key == pygame.K_r:
                    if not show_tech_tree and not show_diplomacy:
                        sel_v = HUD._get_sel_villager(sim)
                        if sel_v:
                            # Cycle through roles
                            roles = list(Role)
                            cur_idx = roles.index(sel_v.role) if sel_v.role in roles else 0
                            next_idx = (cur_idx + 1) % len(roles)
                            old_role = ROLE_NAMES.get(sel_v.role, "?")
                            sel_v.role = roles[next_idx]
                            new_role = ROLE_NAMES.get(sel_v.role, "?")
                            sim.event_log.add(
                                f"{sel_v.name}: {old_role} -> {new_role}",
                                (180, 160, 255),
                            )
                            # If unassigning guard role, remove guard status
                            if sel_v.role != Role.GUARD and sel_v.is_guard:
                                sel_v.is_guard = False
                                if sel_v.fsm and sel_v.fsm.current_state == "guard":
                                    sel_v.fsm.force("idle", sel_v)
                            # If assigning guard role, set guard status
                            if sel_v.role == Role.GUARD and not sel_v.is_guard:
                                sel_v.is_guard = True
                                if sel_v.fsm:
                                    sel_v.fsm.force("guard", sel_v)

                # ── Phase 5: Trade keys (C/Q/E) ──
                elif event.key == pygame.K_c:
                    if not show_tech_tree and not show_diplomacy:
                        msg = sim.trading.execute_trade(0, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                elif event.key == pygame.K_q:
                    if not show_tech_tree and not show_diplomacy:
                        msg = sim.trading.execute_trade(1, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))
                elif event.key == pygame.K_e:
                    if not show_tech_tree and not show_diplomacy:
                        msg = sim.trading.execute_trade(2, sim)
                        if msg:
                            sim.event_log.add(msg, (255, 100, 100))

                # ── Phase 5: Tech tree number keys (1-8) ──
                elif show_tech_tree and event.key in (
                    pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                    pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8,
                ):
                    idx = event.key - pygame.K_1
                    if 0 <= idx < len(_TECH_KEY_ORDER):
                        tech = _TECH_KEY_ORDER[idx]
                        # If pressing key for currently researched tech, cancel
                        if sim.research.current_research == tech:
                            sim.research.cancel_research(sim)
                        elif sim.research.current_research is not None:
                            sim.event_log.add(
                                "Already researching something! Press key on current tech to cancel.",
                                (255, 200, 100),
                            )
                        else:
                            msg = sim.research.start_research(tech, sim)
                            if msg:
                                if "Not enough" in msg:
                                    sim.event_log.add(msg, (255, 100, 100))
                                elif "No Library" in msg:
                                    sim.event_log.add(msg, (255, 100, 100))
                                else:
                                    sim.event_log.add(msg, (180, 200, 255))

                # ── Phase 5: Cancel research in tech tree (X) ──
                elif show_tech_tree and event.key == pygame.K_x:
                    if sim.research.current_research is not None:
                        sim.research.cancel_research(sim)

                # ── Existing controls (only when tech tree is closed) ──
                elif not show_tech_tree:
                    tile_keys = {pygame.K_1: TileType.GRASS, pygame.K_2: TileType.WATER,
                                 pygame.K_3: TileType.SAND, pygame.K_4: TileType.FOREST,
                                 pygame.K_5: TileType.MOUNTAIN, pygame.K_6: TileType.LAVA}
                    build_keys = {
                        pygame.K_7: BuildingType.HOUSE,
                        pygame.K_8: BuildingType.FARM,
                        pygame.K_9: BuildingType.STORAGE,
                        pygame.K_0: BuildingType.WALL,
                        pygame.K_MINUS: BuildingType.GATE,
                    }
                    if event.key in tile_keys:
                        painter.tile_type = tile_keys[event.key]; build_mode = None
                    elif event.key in build_keys:
                        build_mode = build_keys[event.key]
                    elif event.key == pygame.K_RIGHTBRACKET: painter.brush_size = min(painter.brush_size+1, 20)
                    elif event.key == pygame.K_LEFTBRACKET:  painter.brush_size = max(painter.brush_size-1, 0)
                    elif event.key == pygame.K_b:
                        painter.brush_shape = "square" if painter.brush_shape == "circle" else "circle"
                    elif event.key == pygame.K_x: renderer.show_grid = not renderer.show_grid
                    elif event.key == pygame.K_g:
                        # Check if a villager is selected -> toggle guard
                        sel_v = HUD._get_sel_villager(sim)
                        if sel_v:
                            msg = sim.toggle_guard(sel_v)
                            sim.event_log.add(msg, (100, 180, 255))
                        else:
                            generate_terrain(world); sim.rebuild_resource_map()
                    elif event.key == pygame.K_F5: sim.save_resources()
                    elif event.key == pygame.K_F9:
                        if sim.load_resources(): sim.rebuild_resource_map()
                    elif event.key == pygame.K_z and (event.mod & pygame.KMOD_CTRL): painter.undo()
                    elif event.key == pygame.K_v:
                        tx, ty = camera.screen_to_tile(*mouse_pos)
                        v = sim.spawn_villager(tx, ty)
                        if v: print(f"[Sim] Spawned {v.name}")
                        else: print(f"[Sim] Can't spawn at ({tx},{ty})")
                    elif event.key == pygame.K_h:
                        tx, ty = camera.screen_to_tile(*mouse_pos)
                        th = sim.place_town_hall(tx, ty)
                        if not th:
                            if sim.entities.town_hall(): print("[Sim] Town Hall exists")
                            else: print(f"[Sim] Can't place at ({tx},{ty})")
                    elif event.key == pygame.K_space:
                        sim.paused = not sim.paused
                        sim.event_log.add("Paused" if sim.paused else "Resumed", (200,200,100))
                    elif event.key == pygame.K_n:
                        # Debug: trigger a raid
                        sim.raid_number += 1
                        from enemy import spawn_raid
                        spawn_raid(sim, sim.raid_number)
                        sim._raid_active = True

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 4: camera.handle_scroll(1)
                elif event.button == 5: camera.handle_scroll(-1)
                elif event.button == 2:
                    if not minimap.handle_click(screen.get_width(), event.pos, camera):
                        camera.begin_drag(event.pos)
                elif event.button == 1:
                    # Don't interact with world when panels are open
                    if show_tech_tree or show_diplomacy or show_stats:
                        pass
                    elif minimap.handle_click(screen.get_width(), event.pos, camera):
                        pass
                    elif build_mode is not None:
                        tx, ty = camera.screen_to_tile(*event.pos)
                        b = sim.place_building(build_mode, tx, ty)
                        if b: build_mode = None
                    else:
                        tx, ty = camera.screen_to_tile(*event.pos)
                        if entities.select_at_tile(tx, ty) is None:
                            painter.begin_stroke(tx, ty)
                elif event.button == 3:
                    if not show_tech_tree and not show_diplomacy and not show_stats:
                        tx, ty = camera.screen_to_tile(*event.pos)
                        saved = painter.tile_type; painter.tile_type = TileType.GRASS
                        painter.begin_stroke(tx, ty); painter.tile_type = saved

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2: camera.end_drag()
                elif event.button in (1, 3): painter.end_stroke()

            elif event.type == pygame.MOUSEMOTION:
                if camera._dragging: camera.update_drag(event.pos)
                elif not show_tech_tree and not show_diplomacy and not show_stats and pygame.mouse.get_pressed()[0]:
                    if build_mode is None:
                        tx, ty = camera.screen_to_tile(*event.pos)
                        painter.continue_stroke(tx, ty)
                elif not show_tech_tree and not show_diplomacy and not show_stats and pygame.mouse.get_pressed()[2]:
                    tx, ty = camera.screen_to_tile(*event.pos)
                    saved = painter.tile_type; painter.tile_type = TileType.GRASS
                    painter.continue_stroke(tx, ty); painter.tile_type = saved

        keys = pygame.key.get_pressed()
        camera.update(dt, keys, mouse_pos)

        # Phase 6: Don't update sim when game is over
        if not sim.game_over and not sim.victory:
            sim.update(dt)

        # ── draw ──
        renderer.draw(world, camera, game_time)
        if pygame.mouse.get_focused() and not show_tech_tree and not show_diplomacy and not show_stats:
            if build_mode is not None:
                draw_build_preview(screen, camera, build_mode, *mouse_pos, world, entities)
            else:
                renderer.draw_brush_preview(camera, painter, *mouse_pos)

        draw_villagers(screen, entities, camera, sim.tick_frac, hud.font, sim.building_hp)
        draw_enemies(screen, entities, camera, sim.tick_frac, hud.font, sim.building_hp)
        minimap.update(world, entities); minimap._draw_diplomacy_dots(sim); minimap.draw(screen, camera, sim)

        # Weather
        sim.weather.update_particles(dt)
        sim.weather.draw_particles(screen)
        sim.weather.draw_overlay(screen)

        draw_night_overlay(screen, sim)
        cursor_tile = camera.screen_to_tile(*mouse_pos)
        hud.draw(screen, painter, camera, fps, cursor_tile,
                 renderer.show_grid, game_time, sim, build_mode)

        # ── Phase 5 overlays (drawn last, on top of everything) ──
        # Trade offers panel (when merchant is present)
        draw_trade_panel(screen, sim, hud.font, hud.font_sm, hud.font_ev)

        # Tech tree panel (drawn on top of trade panel)
        if show_tech_tree:
            draw_tech_tree(screen, sim, hud.font, hud.font_sm, hud.font_ev)

        # ── Phase 6 overlays ──
        # Achievement popup
        sim.achievements.tick_frame()
        draw_achievement_popup(screen, sim, hud.font, hud.font_sm)

        # Stats panel
        if show_stats:
            draw_stats_panel(screen, sim, hud.font, hud.font_sm, hud.font_ev)

        # Game over / Victory screen (drawn last, on top of everything)
        if sim.game_over or sim.victory:
            draw_game_over(screen, sim, hud.font, hud.font_sm, hud.font_ev)

        pygame.display.flip()

    pygame.quit(); sys.exit()


if __name__ == "__main__":
    main()