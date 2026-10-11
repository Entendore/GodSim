"""
simulation.py — Fixed-timestep tick loop, resource map, day/night cycle,
weather, construction, farm production, enemy raids, combat, auto-population,
and event log.
"""

from __future__ import annotations

import math
import time as _time
import random
from collections import deque
from typing import Optional, Dict, List, Tuple

import numpy as np

from config import (
    TILE_SIZE, WORLD_W, WORLD_H, TileType, SAVE_PATH,
    BuildingType, BUILDING_DEFS,
    DAY_LENGTH, DAWN_END, DAY_END, DUSK_END,
    ENEMY_SPAWN_MIN_TICKS, ENEMY_SPAWN_MAX_TICKS,
)
from entities import EntityManager, Entity, Building
from weather import WeatherManager
from research import ResearchManager
from trading import TradingManager
from diplomacy import DiplomacyManager
from config import Tech, TECH_DEFS
from achievements import AchievementManager
from buildings_upgrade import add_upgrade_tick, apply_upgrade_effects
from sounds import SoundManager


# ──────────────────────────────────────────────
#  Event Log
# ──────────────────────────────────────────────
class EventLog:
    """Rolling log of simulation events for the HUD."""

    MAX = 80

    def __init__(self) -> None:
        self.entries: deque = deque(maxlen=self.MAX)

    def add(self, text: str, color: Tuple[int, int, int] = (210, 210, 210)) -> None:
        self.entries.append((text, color))


# ──────────────────────────────────────────────
#  Day / Night helpers
# ──────────────────────────────────────────────
def get_day_phase(sim_time: float) -> str:
    frac = (sim_time % DAY_LENGTH) / DAY_LENGTH
    if frac < DAWN_END:
        return "dawn"
    elif frac < DAY_END:
        return "day"
    elif frac < DUSK_END:
        return "dusk"
    return "night"


def get_night_overlay_alpha(sim_time: float) -> int:
    """Return an alpha value [0, 80] for the full-screen night overlay."""
    frac = (sim_time % DAY_LENGTH) / DAY_LENGTH
    if frac < DAWN_END:
        return int(70 * (1.0 - frac / DAWN_END))
    elif frac < DAY_END:
        return 0
    elif frac < DUSK_END:
        t = (frac - DAY_END) / (DUSK_END - DAY_END)
        return int(55 * t)
    else:
        night_frac = (frac - DUSK_END) / (1.0 - DUSK_END)
        return int(55 + 20 * math.sin(night_frac * math.pi))


def get_night_tint(sim_time: float) -> Tuple[int, int, int, int]:
    """Return (R, G, B, A) for the overlay."""
    phase = get_day_phase(sim_time)
    alpha = get_night_overlay_alpha(sim_time)
    if phase == "dawn":
        return (200, 140, 80, alpha)
    elif phase == "dusk":
        return (140, 80, 140, alpha)
    else:
        return (15, 15, 60, alpha)


# ──────────────────────────────────────────────
#  Simulation Manager
# ──────────────────────────────────────────────
class SimulationManager:
    """Owns the entity manager, resource map, tick loop, and all
    simulation subsystems."""

    def __init__(self, world, entities: EntityManager, screen_w: int = 1280, screen_h: int = 800) -> None:
        self.world = world
        self.entities = entities

        # Tick
        self.tick_rate: float = 10.0
        self.tick_interval: float = 1.0 / self.tick_rate
        self.accumulator: float = 0.0
        self.tick_frac: float = 0.0
        self.paused: bool = False
        self.total_ticks: int = 0

        # Sim clock (seconds of simulated time, always advancing when unpaused)
        self.sim_time: float = 0.0

        # Resources
        self.resource_map: np.ndarray = np.zeros(
            (world.h, world.w), dtype=np.int32
        )
        self._init_resource_map()
        self.global_resources: Dict[str, int] = {"food": 10, "stone": 0}

        # Stats
        self.stats: Dict[str, int] = {}

        # Event log
        self.event_log = EventLog()

        # Auto-population
        self._birth_cooldown: int = 0

        # Weather
        self.weather = WeatherManager(screen_w, screen_h)

        # Building HP tracking (building_id -> current_hp)
        self.building_hp: Dict[int, int] = {}

        # Research, Trading, Diplomacy
        self.research = ResearchManager()
        self.trading = TradingManager()
        self.diplomacy = DiplomacyManager()

        # Phase 6: Achievements & Sounds
        self.achievements = AchievementManager()
        self.sounds = SoundManager()

        # Game over state
        self.game_over: bool = False
        self.game_over_reason: str = ""
        self.victory: bool = False

        # Enemy raid system
        self.raid_number: int = 0
        self._raid_cooldown: int = random.randint(
            ENEMY_SPAWN_MIN_TICKS, ENEMY_SPAWN_MAX_TICKS
        )
        self._raid_active: bool = False

        # Death cooldown to prevent rapid re-population
        self._death_cooldown: int = 0

    # ── resource map ─────────────────────────────
    def _init_resource_map(self) -> None:
        forest_mask = self.world.tiles == TileType.FOREST
        self.resource_map[forest_mask] = np.random.randint(
            5, 16, size=int(forest_mask.sum())
        )

    def rebuild_resource_map(self) -> None:
        forest_mask = (self.world.tiles == TileType.FOREST) & (self.resource_map <= 0)
        count = int(forest_mask.sum())
        if count > 0:
            self.resource_map[forest_mask] = np.random.randint(5, 16, size=count)

    # ── main update (called every frame) ─────────
    def update(self, dt: float) -> None:
        if self.paused:
            self.tick_frac = 0.0
            return

        self.sim_time += dt
        self.accumulator += dt
        if self.accumulator > 0.5:
            self.accumulator = 0.5

        while self.accumulator >= self.tick_interval:
            self.accumulator -= self.tick_interval
            self._tick()
            self.total_ticks += 1

        self.tick_frac = self.accumulator / self.tick_interval

    # ── single simulation tick ───────────────────
    def _tick(self) -> None:
        from villager import Villager
        from enemy import Enemy

        # Weather tick
        self.weather.tick()

        # Save previous positions
        for e in self.entities.all():
            if e.alive:
                e.save_prev()

        # Update villagers
        for e in self.entities.all():
            if not e.alive or isinstance(e, Building) or isinstance(e, Enemy):
                continue
            v: Villager = e
            v._sim = self
            if v.fsm is not None:
                v.fsm.tick(v, self)

        # Update enemies
        for e in self.entities.all():
            if not isinstance(e, Enemy) or not e.alive:
                continue
            en: Enemy = e
            en.tick_ai(self)

        self.entities.cull_dead()

        # Periodic world systems
        self._tick_farms()
        self._tick_upgrades()
        self._tick_auto_research()
        self._tick_auto_population()
        self._tick_warnings()
        self._tick_raid_spawner()
        self._check_raid_clear()
        self.diplomacy.tick(self)
        self._tick_allied_reinforcements()
        self.achievements.check(self)

        # Phase 6: Check defeat / victory
        if not self.game_over and not self.victory:
            if self.achievements.check_defeat(self):
                self.game_over = True
                self.game_over_reason = "All villagers have perished. Your village is no more."
                self.event_log.add("DEFEAT: " + self.game_over_reason, (255, 50, 50))
                self.sounds.play("defeat")
            elif self.achievements.check_victory(self):
                self.victory = True
                self.event_log.add("VICTORY! Your village has become a thriving civilization!", (255, 215, 0))
                self.sounds.play("victory")

        # Death cooldown
        if self._death_cooldown > 0:
            self._death_cooldown -= 1

    # ── farm production (passive) ────────────────
    def _tick_farms(self) -> None:
        for b in self.entities.completed_buildings():
            if b.btype == BuildingType.FARM:
                produced = b.tick_farm()
                if produced:
                    farm_mult = self.weather.farm_mult
                    if self.research.has_farm_bonus():
                        farm_mult *= 2.0
                    actual = max(1, int(produced * farm_mult))
                    self.global_resources["food"] = self.global_resources.get("food", 0) + actual
                    self.stats["food_produced"] = self.stats.get("food_produced", 0) + actual

    # ── building upgrades (Phase 6) ──────────────
    def _tick_upgrades(self) -> None:
        """Auto-advance upgrading buildings when builders are nearby."""
        for b in self.entities.upgrading_buildings():
            # Check if any builder-role villager is adjacent to this building
            tx0, ty0, tx1, ty1 = b.tile_rect
            from villager import Villager
            from config import Role
            has_builder = False
            for e in self.entities.all():
                if isinstance(e, Villager) and e.alive:
                    if e.role == Role.BUILDER or e.role == Role.NONE:
                        if (tx0 - 2 <= e.tile_x <= tx1 + 1
                                and ty0 - 2 <= e.tile_y <= ty1 + 1):
                            has_builder = True
                            break
            if has_builder:
                done = add_upgrade_tick(b)
                if done:
                    apply_upgrade_effects(b, self)
                    self.sounds.play("upgrade")

    # ── enemy raid spawning ──────────────────────
    def _tick_raid_spawner(self) -> None:
        if self._raid_active:
            return
        if self.entities.town_hall() is None:
            return
        if self.population < 2:
            return  # Don't raid before village is established

        self._raid_cooldown -= 1
        if self._raid_cooldown <= 0:
            self.raid_number += 1
            from enemy import spawn_raid
            enemies = spawn_raid(self, self.raid_number)
            if enemies:
                self._raid_active = True
                self.event_log.add(
                    f"Raid #{self.raid_number} incoming!",
                    (255, 60, 60),
                )
                self.sounds.play("raid")
            # Reset cooldown (raids get more frequent over time)
            base = random.randint(ENEMY_SPAWN_MIN_TICKS, ENEMY_SPAWN_MAX_TICKS)
            self._raid_cooldown = max(100, int(base / (1 + self.raid_number * 0.1)))

    def _check_raid_clear(self) -> None:
        """Check if the current raid has been repelled."""
        if not self._raid_active:
            return
        from enemy import Enemy
        for e in self.entities.all():
            if isinstance(e, Enemy) and e.alive:
                return  # Still enemies alive
        # Raid cleared
        self._raid_active = False
        self.stats["raids_survived"] = self.stats.get("raids_survived", 0) + 1
        self.event_log.add(
            f"Raid #{self.raid_number} repelled!",
            (100, 255, 100),
        )
        # Bonus food for surviving
        bonus = 3 + self.raid_number
        self.global_resources["food"] = self.global_resources.get("food", 0) + bonus
        self.event_log.add(f"+{bonus} food as spoils of victory!", (200, 200, 100))

    # ── allied reinforcements ──────────────────
    def _tick_allied_reinforcements(self) -> None:
        """When a raid starts, allied villages may send temporary guards."""
        if not self._raid_active:
            return
        # Only trigger once per raid — use a flag
        if getattr(self, "_reinforcements_sent_for_raid", 0) == self.raid_number:
            return
        count = self.diplomacy.get_allied_reinforcements(self)
        if count <= 0:
            return
        self._reinforcements_sent_for_raid = self.raid_number
        th = self.entities.town_hall()
        if th is None:
            return
        from villager import Villager
        from config import Role
        tx = th.origin_tx + th.width_tiles // 2
        ty = th.origin_ty + th.height_tiles // 2
        for _ in range(count):
            v = self._spawn_at(tx, ty)
            if v:
                v.is_guard = True
                v.role = Role.GUARD
                if v.fsm:
                    v.fsm.force("guard", v)
        self.event_log.add(
            f"Allied reinforcements: {count} guard(s) arrived!",
            (80, 200, 255),
        )
        self.sounds.play("build_complete")
        self.stats["reinforcements_received"] = self.stats.get("reinforcements_received", 0) + count

    # ── auto-research ──────────────────────────
    def _tick_auto_research(self) -> None:
        if self.research.current_research is not None:
            self.research.tick(self)
            return
        # Auto-start research if scholars are present and techs available
        from villager import Villager
        from config import Role
        scholars = sum(1 for e in self.entities.all()
                       if isinstance(e, Villager) and e.alive and e.role == Role.SCHOLAR)
        if scholars > 0:
            available = self.research.available_techs()
            if available:
                # Pick the cheapest available tech
                best = min(available, key=lambda t: sum(TECH_DEFS[t]["cost"].values()))
                msg = self.research.start_research(best, self)
                if msg and "Not enough" not in msg:
                    self.event_log.add(msg, (180, 160, 255))

        # Also tick trading
        self.trading.tick(self)

    # ── auto-population ──────────────────────────
    def _tick_auto_population(self) -> None:
        if self._birth_cooldown > 0:
            self._birth_cooldown -= 1
            return
        if self._death_cooldown > 0:
            return

        pop = self.population
        cap = self.entities.pop_cap()
        food = self.global_resources.get("food", 0)

        if pop >= cap or pop < 2 or food < 10:
            return

        if random_chance(0.002):
            th = self.entities.town_hall()
            if th is None:
                return
            self.global_resources["food"] = food - 5
            tx = th.origin_tx + th.width_tiles // 2
            ty = th.origin_ty + th.height_tiles // 2
            v = self._spawn_at(tx, ty)
            if v:
                self.event_log.add(f"A child was born: {v.name}!", (255, 220, 150))
                self._birth_cooldown = 50

    # ── warnings ─────────────────────────────────
    _warn_food_cd: int = 0
    _warn_pop_cd: int = 0
    _warn_raid_cd: int = 0

    def _tick_warnings(self) -> None:
        if self._warn_food_cd > 0:
            self._warn_food_cd -= 1
        if self._warn_pop_cd > 0:
            self._warn_pop_cd -= 1
        if self._warn_raid_cd > 0:
            self._warn_raid_cd -= 1

        food = self.global_resources.get("food", 0)
        if food < 3 and self.population > 0 and self._warn_food_cd == 0:
            self.event_log.add("Food supplies critically low!", (255, 100, 100))
            self._warn_food_cd = 100

        if self.population >= self.entities.pop_cap() and self._warn_pop_cd == 0 and self.population > 0:
            self.event_log.add("Population at capacity — build more houses!", (255, 200, 100))
            self._warn_pop_cd = 200

        # Weather warning
        from config import Weather
        if self.weather.current == Weather.STORM and self._warn_raid_cd == 0:
            self.event_log.add("A storm rages! Movement and farming reduced.", (150, 150, 255))
            self._warn_raid_cd = 150

    # ── spawning helpers ─────────────────────────
    def spawn_villager(self, tx: int, ty: int) -> Optional[object]:
        if not self.world.in_bounds(tx, ty):
            return None
        from config import WALKABLE_TILES
        if self.world.get(tx, ty) not in WALKABLE_TILES:
            return None
        v = self._spawn_at(tx, ty)
        if v:
            self.event_log.add(f"{v.name} has joined the village.", (150, 220, 255))
        return v

    def _spawn_at(self, tx: int, ty: int) -> Optional[object]:
        from villager import Villager
        wx = tx * TILE_SIZE + TILE_SIZE * 0.5
        wy = ty * TILE_SIZE + TILE_SIZE * 0.5
        v = Villager(wx, wy)
        v.build_fsm()
        self.entities.add(v)
        return v

    def place_building(self, btype: BuildingType, tx: int, ty: int) -> Optional[Building]:
        """Place a building (possibly under construction) if valid."""
        defn = BUILDING_DEFS[btype]
        w, h = defn["w"], defn["h"]
        cost = dict(defn["cost"])

        # Town hall: only one, no cost
        if btype == BuildingType.TOWN_HALL:
            if self.entities.town_hall() is not None:
                return None
        else:
            for res, amt in cost.items():
                if self.global_resources.get(res, 0) < amt:
                    self.event_log.add(
                        f"Not enough {res}! Need {amt}, have {self.global_resources.get(res, 0)}.",
                        (255, 100, 100),
                    )
                    return None

        # Check footprint is all grass (or any walkable for non-town-hall)
        for dy in range(h):
            for dx in range(w):
                cx, cy = tx + dx, ty + dy
                if not self.world.in_bounds(cx, cy):
                    return None
                if self.world.get(cx, cy) != TileType.GRASS:
                    return None

        # Deduct cost
        for res, amt in cost.items():
            self.global_resources[res] = self.global_resources.get(res, 0) - amt

        instant = (btype == BuildingType.TOWN_HALL)
        b = Building(
            tx, ty,
            width_tiles=w, height_tiles=h,
            name=defn["name"],
            color=defn["color"],
            btype=btype,
            cost=cost,
        )
        b.built = instant
        b.construction_progress = 1.0 if instant else 0.0
        self.entities.add(b)

        if instant:
            max_hp = defn.get("hp", 100)
            self.building_hp[b.id] = max_hp
            self.event_log.add(f"{b.name} placed.", (200, 200, 100))
            self.sounds.play("place")
        else:
            self.event_log.add(
                f"Construction started: {b.name} (cost: {cost})",
                (200, 180, 100),
            )
            self.sounds.play("build_start")
        return b

    def place_town_hall(self, tx: int, ty: int) -> Optional[Building]:
        return self.place_building(BuildingType.TOWN_HALL, tx, ty)

    def toggle_guard(self, villager) -> Optional[str]:
        """Toggle guard assignment on a villager. Returns status message."""
        if villager.is_guard:
            villager.is_guard = False
            if villager.fsm and villager.fsm.current_state == "guard":
                villager.fsm.force("idle", villager)
            return f"{villager.name} removed from guard duty."
        else:
            villager.is_guard = True
            if villager.fsm:
                villager.fsm.force("guard", villager)
            return f"{villager.name} assigned as guard!"

    # ── save / load ──────────────────────────────
    def save_resources(self, path: str = SAVE_PATH) -> None:
        np.savez_compressed(
            path,
            tiles=self.world.tiles,
            variation=self.world.variation,
            resource_map=self.resource_map,
        )
        self.event_log.add("World saved.", (150, 200, 255))

    def load_resources(self, path: str = SAVE_PATH) -> bool:
        import os
        if not os.path.exists(path):
            return False
        data = np.load(path)
        self.world.tiles[:] = data["tiles"]
        self.world.variation[:] = data["variation"]
        self.world._dirty = True
        if "resource_map" in data:
            self.resource_map[:] = data["resource_map"]
        else:
            self._init_resource_map()
        self.event_log.add("World loaded.", (150, 200, 255))
        return True

    # ── stats ────────────────────────────────────
    @property
    def population(self) -> int:
        from enemy import Enemy
        return len([e for e in self.entities.all()
                     if e.alive and not isinstance(e, Building) and not isinstance(e, Enemy)])

    @property
    def enemy_count(self) -> int:
        from enemy import Enemy
        return len([e for e in self.entities.all() if isinstance(e, Enemy) and e.alive])

    @property
    def guard_count(self) -> int:
        from villager import Villager
        return len([e for e in self.entities.all()
                     if isinstance(e, Villager) and e.alive and e.is_guard])

    @property
    def day_number(self) -> int:
        return int(self.sim_time // DAY_LENGTH) + 1

    @property
    def day_phase(self) -> str:
        return get_day_phase(self.sim_time)


def random_chance(p: float) -> bool:
    return random.random() < p