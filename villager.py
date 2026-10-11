"""
villager.py — Villager entity, FSM states, rendering.

States
------
idle           — think, then choose: build / gather / eat / mine / guard / wander / rest
wander         — walk to a random nearby tile
gather         — move to forest, harvest wood
mine           — move to mountain, harvest stone
rest           — recover energy
return_to_base — carry resources back to town hall
build          — walk to an unfinished building, construct it
farm_work      — walk to a completed farm, work it for food
eat            — go to town hall to consume food from global pool
guard          — patrol near town hall, attack enemies on sight
flee           — run away from nearby enemies (low HP)

Pathfinding: delegates to pathfinding.astar (A* with octile heuristic).
"""

from __future__ import annotations

import math
import random
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING

import pygame

from config import (
    TILE_SIZE, WORLD_W, WORLD_H, TileType, WALKABLE_TILES,
    BuildingType, Role, role_efficiency,
    VILLAGER_BASE_HEALTH, VILLAGER_BASE_DAMAGE,
    VILLAGER_ATTACK_COOLDOWN, GUARD_DAMAGE_BONUS,
)
from entities import Entity, Building
from fsm import State
from pathfinding import find_path, is_walkable

if TYPE_CHECKING:
    from simulation import SimulationManager

# ════════════════════════════════════════════════
#  Names pool
# ════════════════════════════════════════════════
FIRST_NAMES = [
    "Aldric", "Brenna", "Cedric", "Daria", "Edmund",
    "Fiona", "Gareth", "Helena", "Ivan", "Johanna",
    "Kaelen", "Liora", "Magnus", "Nora", "Orin",
    "Petra", "Quinn", "Rowan", "Sable", "Theron",
    "Uma", "Vance", "Wren", "Xara", "Yara", "Zev",
]


# ════════════════════════════════════════════════
#  Villager
# ════════════════════════════════════════════════
class Villager(Entity):
    """An autonomous villager with FSM-driven AI."""

    def __init__(self, wx: float, wy: float, name: Optional[str] = None) -> None:
        super().__init__(wx, wy, name or random.choice(FIRST_NAMES))
        self.speed: float = 2.5
        self.path: List[Tuple[int, int]] = []
        self.facing: float = 0.0

        # Combat
        self.max_hp: int = VILLAGER_BASE_HEALTH
        self.hp: int = VILLAGER_BASE_HEALTH
        self.damage: int = VILLAGER_BASE_DAMAGE
        self._attack_cd: int = 0
        self.is_guard: bool = False  # assigned as guard
        self.role: Role = Role.NONE  # specialization

        # Needs
        self.energy: float = 100.0
        self.max_energy: float = 100.0
        self.energy_decay: float = 0.15
        self.energy_regen: float = 3.0

        # Hunger (0-100, 0=full, 100=starving)
        self.hunger: float = 0.0
        self.max_hunger: float = 100.0
        self.hunger_rate: float = 0.10     # per tick
        self.hunger_eat_amount: float = 35.0  # hunger reduced per meal

        # Inventory
        self.inventory: Dict[str, int] = {}
        self.max_carry: int = 10

        # Internal timer (ticks)
        self._timer: int = 0

        # Simulation ref — set each tick by SimulationManager
        self._sim: Optional[SimulationManager] = None  # type: ignore

        # FSM
        self.fsm = None  # type: ignore

    def build_fsm(self) -> None:
        from fsm import StateMachine
        self.fsm = (
            StateMachine()
            .add(IdleState())
            .add(WanderState())
            .add(GatherState())
            .add(MineState())
            .add(RestState())
            .add(ReturnToBaseState())
            .add(BuildState())
            .add(FarmWorkState())
            .add(EatState())
            .add(GuardState())
            .add(FleeState())
            .add(ResearchState())
        )
        self.fsm.start("idle", self)

    # ── path following ────────────────────────────
    def set_path(self, path: List[Tuple[int, int]]) -> None:
        self.path = list(path)

    def has_path(self) -> bool:
        return len(self.path) > 0

    def follow_path_tick(self, tick_rate: float, move_mult: float = 1.0) -> bool:
        if not self.path:
            return True
        step = self.speed * TILE_SIZE / tick_rate * move_mult
        arrived = self.move_toward_tile(self.path[0][0], self.path[0][1], step)
        if arrived:
            self.path.pop(0)
            if self.path:
                dx = self.path[0][0] * TILE_SIZE - self.x
                dy = self.path[0][1] * TILE_SIZE - self.y
                if abs(dx) + abs(dy) > 1:
                    self.facing = math.atan2(dy, dx)
        if not self.path:
            return True
        return False

    def clear_path(self) -> None:
        self.path.clear()

    # ── needs ─────────────────────────────────────
    def tick_needs(self, sim: "SimulationManager" = None) -> None:
        self.energy = max(0.0, self.energy - self.energy_decay)
        self.hunger = min(self.max_hunger, self.hunger + self.hunger_rate)
        # Starving: extra energy drain
        if self.hunger > 80:
            self.energy = max(0.0, self.energy - 0.1)
        # Medicine: faster rest healing
        if sim and hasattr(sim, 'research') and sim.research.has_medicine_bonus():
            self.hp = min(self.max_hp, self.hp + 0.2)

    # ── combat ────────────────────────────────────
    def take_damage(self, dmg: int) -> bool:
        """Returns True if killed."""
        self.hp -= dmg
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def try_attack_enemy(self, enemy, sim: "SimulationManager") -> bool:
        """Attempt to attack an enemy in range. Returns True if attacked."""
        if self._attack_cd > 0:
            return False
        dx = enemy.x - self.x
        dy = enemy.y - self.y
        dist = math.hypot(dx, dy)
        attack_range = 1.5 * TILE_SIZE
        # Archery tech: +1 tile range
        if hasattr(sim, 'research') and sim.research.has_range_bonus():
            attack_range += 1.0 * TILE_SIZE
        if dist > attack_range:
            return False

        combat_mult = sim.weather.combat_mult if hasattr(sim, "weather") else 1.0
        role_mult = role_efficiency(self.role, "combat_damage")
        dmg = max(1, int(self.damage * role_mult * combat_mult))
        self._attack_cd = VILLAGER_ATTACK_COOLDOWN
        self.facing = math.atan2(dy, dx)

        killed = enemy.take_damage(dmg)
        if killed:
            sim.event_log.add(
                f"{self.name} slew {enemy.name}!",
                (100, 255, 100),
            )
            sim.stats["enemies_killed"] = sim.stats.get("enemies_killed", 0) + 1
            sim.sounds.play("enemy_death")
            # Loot
            loot_stone = random.randint(0, 2)
            if loot_stone > 0:
                sim.global_resources["stone"] = sim.global_resources.get("stone", 0) + loot_stone
            sim.global_resources["food"] = sim.global_resources.get("food", 0) + 1
        return True

    # ── inventory ─────────────────────────────────
    def carry_count(self) -> int:
        return sum(self.inventory.values())

    def is_overencumbered(self) -> bool:
        return self.carry_count() >= self.max_carry


# ════════════════════════════════════════════════
#  FSM States
# ════════════════════════════════════════════════

def _check_critical(v: Villager, sim: "SimulationManager") -> Optional[str]:
    """Shared priority checks used by most states."""
    if v.hp < v.max_hp * 0.2 and not v.is_guard:
        return "flee"
    if v.energy < 12:
        return "rest"
    if v.hunger > 85 and sim.entities.town_hall() is not None:
        food = sim.global_resources.get("food", 0)
        if food > 0:
            return "eat"
    if v.is_overencumbered() and sim.entities.town_hall() is not None:
        return "return_to_base"
    return None


def _check_enemy_threat(v: Villager, sim: "SimulationManager") -> Optional[str]:
    """If enemies are nearby, guards engage, others flee."""
    from enemy import Enemy
    nearby_enemies = []
    for e in sim.entities.all():
        if isinstance(e, Enemy) and e.alive:
            d = math.hypot(e.x - v.x, e.y - v.y)
            if d < 6 * TILE_SIZE:
                nearby_enemies.append(e)
    if not nearby_enemies:
        return None
    if v.is_guard:
        return "guard"
    if v.hp < v.max_hp * 0.4:
        return "flee"
    return None


def _get_entities(sim: "SimulationManager"):
    """Helper to pass entities to pathfinding."""
    return sim.entities


class IdleState(State):
    @property
    def name(self) -> str:
        return "idle"

    def enter(self, v: Villager) -> None:
        v.clear_path()
        v._timer = random.randint(5, 20)

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v._timer -= 1
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1

        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat

        crit = _check_critical(v, sim)
        if crit:
            return crit
        if v.energy < 20:
            return "rest"

        if v._timer > 0:
            return None

        # Guard check
        if v.is_guard:
            return "guard"

        # Scholar: go research if research is available
        if v.role == Role.SCHOLAR and hasattr(sim, 'research'):
            if sim.research.current_research is not None:
                return "research"
            elif sim.research.available_techs():
                return "research"

        # Role-based priority
        if v.role == Role.BUILDER:
            unfinished = sim.entities.unfinished_buildings()
            if unfinished:
                return "build"

        if v.role == Role.FARMER:
            farms = sim.entities.farms()
            if farms and sim.global_resources.get("food", 0) < sim.population * 8:
                return "farm_work"

        if v.role == Role.LUMBERJACK:
            target = _find_nearest_forest(v, sim, radius=15)
            if target is not None and not v.is_overencumbered():
                return "gather"

        if v.role == Role.MINER:
            mine = _find_nearest_mountain(v, sim, radius=15)
            if mine is not None and not v.is_overencumbered():
                return "mine"

        # Generic priority (same as before)
        # 1. Unfinished building?
        unfinished = sim.entities.unfinished_buildings()
        if unfinished:
            return "build"

        # 2. Hunger
        if v.hunger > 60 and sim.global_resources.get("food", 0) > 0:
            if sim.entities.town_hall() is not None:
                return "eat"

        # 3. Farm if food low
        farms = sim.entities.farms()
        if farms and sim.global_resources.get("food", 0) < sim.population * 5:
            return "farm_work"

        # 4. Gather or mine
        target = _find_nearest_forest(v, sim, radius=12)
        mine = _find_nearest_mountain(v, sim, radius=12)
        if target is not None and mine is not None:
            if random.random() < 0.5:
                return "gather"
            else:
                return "mine"
        elif target is not None:
            if random.random() < 0.45:
                return "gather"
        elif mine is not None:
            if random.random() < 0.35:
                return "mine"

        return "wander"

    def exit(self, v: Villager) -> None:
        pass


class WanderState(State):
    @property
    def name(self) -> str:
        return "wander"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None:
            return
        radius = random.randint(5, 15)
        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(3, radius)
        tx = max(0, min(int(v.tile_x + dist * math.cos(angle)), WORLD_W - 1))
        ty = max(0, min(int(v.tile_y + dist * math.sin(angle)), WORLD_H - 1))
        ents = _get_entities(sim)
        if is_walkable(sim.world, tx, ty, ents):
            v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
        else:
            v.set_path(_find_any_walkable(v, sim, radius))

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        crit = _check_critical(v, sim)
        if crit:
            return crit
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat
        move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
        if v.follow_path_tick(sim.tick_rate, move_mult):
            return "idle"
        return None

    def exit(self, v: Villager) -> None:
        pass


class GatherState(State):
    @property
    def name(self) -> str:
        return "gather"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None:
            v._timer = -1
            return
        target = _find_nearest_forest(v, sim, radius=20)
        if target is not None:
            ents = _get_entities(sim)
            v.set_path(find_path((v.tile_x, v.tile_y), target, sim.world, entities=ents))
            v._timer = 0
        else:
            v.clear_path()
            v._timer = -1

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        if v.energy < 10:
            return "rest"
        if v.is_overencumbered() and sim.entities.town_hall() is not None:
            return "return_to_base"
        if v._timer == -1:
            return "idle"
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat

        if v.has_path():
            move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 0
            return None

        tx, ty = v.tile_x, v.tile_y
        if sim.world.get(tx, ty) != TileType.FOREST:
            return "idle"
        if sim.resource_map[ty, tx] <= 0:
            return "idle"

        sim.resource_map[ty, tx] -= 1
        # Role + tech bonus: may harvest extra
        eff = role_efficiency(v.role, "gather_wood")
        gather_bonus = 1.0
        if hasattr(sim, 'research') and sim.research.has_gather_bonus():
            gather_bonus = 1.5
        total = eff * gather_bonus
        amount = 1
        if total >= 2.0 and random.random() < (total - 1.0):
            amount = 2
        v.inventory["wood"] = v.inventory.get("wood", 0) + amount
        sim.stats["wood_gathered"] = sim.stats.get("wood_gathered", 0) + amount

        if sim.resource_map[ty, tx] <= 0:
            sim.world.set(tx, ty, TileType.GRASS)
            sim.world._dirty = True

        if v.is_overencumbered():
            return "return_to_base" if sim.entities.town_hall() else "idle"
        return None

    def exit(self, v: Villager) -> None:
        pass


class MineState(State):
    """Move to a mountain tile and harvest stone (or iron with metallurgy)."""

    @property
    def name(self) -> str:
        return "mine"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None:
            v._timer = -1
            return
        target = _find_nearest_mountain(v, sim, radius=20)
        if target is not None:
            ents = _get_entities(sim)
            v.set_path(find_path((v.tile_x, v.tile_y), target, sim.world, entities=ents))
            v._timer = 0
        else:
            v.clear_path()
            v._timer = -1

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        if v.energy < 10:
            return "rest"
        if v.is_overencumbered() and sim.entities.town_hall() is not None:
            return "return_to_base"
        if v._timer == -1:
            return "idle"
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat

        if v.has_path():
            move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 0
            return None

        tx, ty = v.tile_x, v.tile_y
        if sim.world.get(tx, ty) != TileType.MOUNTAIN:
            return "idle"

        eff = role_efficiency(v.role, "mine_stone")
        gather_bonus = 1.0
        if hasattr(sim, 'research') and sim.research.has_gather_bonus():
            gather_bonus = 1.5
        total = eff * gather_bonus

        # Mining: 60% base chance per tick
        if random.random() < 0.6 * total:
            # Iron with metallurgy tech (30% chance when available)
            has_metal = hasattr(sim, 'research') and sim.research.has_metallurgy()
            if has_metal and random.random() < 0.3:
                v.inventory["iron"] = v.inventory.get("iron", 0) + 1
                sim.stats["iron_mined"] = sim.stats.get("iron_mined", 0) + 1
            else:
                v.inventory["stone"] = v.inventory.get("stone", 0) + 1
                sim.stats["stone_mined"] = sim.stats.get("stone_mined", 0) + 1

            if random.random() < 0.03:
                sim.world.set(tx, ty, TileType.SAND)
                sim.world._dirty = True

        if v.is_overencumbered():
            return "return_to_base" if sim.entities.town_hall() else "idle"
        return None

    def exit(self, v: Villager) -> None:
        pass


class RestState(State):
    @property
    def name(self) -> str:
        return "rest"

    def enter(self, v: Villager) -> None:
        v.clear_path()

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        regen = v.energy_regen
        if hasattr(sim, 'research') and sim.research.has_medicine_bonus():
            regen *= 1.5
        v.energy = min(v.max_energy, v.energy + regen)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat
        if v.energy >= v.max_energy * 0.95:
            crit = _check_critical(v, sim)
            if crit:
                return crit
            return "wander"
        return None

    def exit(self, v: Villager) -> None:
        pass


class ReturnToBaseState(State):
    @property
    def name(self) -> str:
        return "return_to_base"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None or sim.entities.town_hall() is None:
            v.clear_path()
            v._timer = -1
            return
        th = sim.entities.town_hall()
        tx = th.origin_tx + th.width_tiles // 2
        ty = th.origin_ty + th.height_tiles // 2
        ents = _get_entities(sim)
        v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
        v._timer = 0

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        if v._timer == -1:
            return "idle"
        move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
        if v.has_path():
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 1
            return None
        if v._timer == 1:
            for res, amt in v.inventory.items():
                sim.global_resources[res] = sim.global_resources.get(res, 0) + amt
            v.inventory.clear()
            v._timer = 0
            return "idle"
        return None

    def exit(self, v: Villager) -> None:
        pass


class BuildState(State):
    """Walk to the oldest unfinished building and construct it."""

    @property
    def name(self) -> str:
        return "build"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None:
            v._timer = -1
            return
        unfinished = sim.entities.unfinished_buildings()
        if not unfinished:
            v._timer = -1
            return
        b = unfinished[0]
        tx = b.origin_tx + b.width_tiles // 2
        ty = b.origin_ty + b.height_tiles // 2
        ents = _get_entities(sim)
        v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
        v._timer = 0

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        if v.energy < 10:
            return "rest"
        if v.hunger > 90 and sim.global_resources.get("food", 0) > 0:
            return "eat"
        if v._timer == -1:
            return "idle"
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat

        unfinished = sim.entities.unfinished_buildings()
        move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0

        if v.has_path():
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 0
            return None

        # At site — build one tick
        if unfinished:
            b = unfinished[0]
            tx0, ty0, tx1, ty1 = b.tile_rect
            if not (tx0 - 1 <= v.tile_x <= tx1 and ty0 - 1 <= v.tile_y <= ty1):
                tx = b.origin_tx + b.width_tiles // 2
                ty = b.origin_ty + b.height_tiles // 2
                ents = _get_entities(sim)
                v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
                return None
            # Builder role: 2x construction speed
            build_eff = role_efficiency(v.role, "build_speed")
            for _ in range(int(build_eff)):
                done = b.add_construction_tick()
                if done:
                    break
            if done:
                b.built = True
                hp_base = b.defn.get("hp", 100)
                # Fortify bonus
                if hasattr(sim, 'research') and sim.research.has_fortify_bonus():
                    hp_base = int(hp_base * 1.5)
                sim.building_hp[b.id] = hp_base
                sim.event_log.add(f"{b.name} completed!", (100, 255, 100))
                sim.stats["buildings_completed"] = sim.stats.get("buildings_completed", 0) + 1
                sim.sounds.play("build_complete")
                return "idle"
        else:
            return "idle"
        return None

    def exit(self, v: Villager) -> None:
        pass


class FarmWorkState(State):
    """Walk to a completed farm and work it (produces food)."""

    @property
    def name(self) -> str:
        return "farm_work"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None:
            v._timer = -1
            return
        farms = sim.entities.farms()
        if not farms:
            v._timer = -1
            return
        best, best_d = None, float("inf")
        for f in farms:
            d = abs(f.origin_tx - v.tile_x) + abs(f.origin_ty - v.tile_y)
            if d < best_d:
                best_d = d
                best = f
        b = best
        tx = b.origin_tx + b.width_tiles // 2
        ty = b.origin_ty + b.height_tiles // 2
        ents = _get_entities(sim)
        v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
        v._timer = 0

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        crit = _check_critical(v, sim)
        if crit:
            return crit
        if v._timer == -1:
            return "idle"
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat

        farms = sim.entities.farms()
        move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0

        if v.has_path():
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 0
            return None

        if not farms:
            return "idle"
        b = farms[0]
        tx0, ty0, tx1, ty1 = b.tile_rect
        if not (tx0 - 1 <= v.tile_x <= tx1 and ty0 - 1 <= v.tile_y <= ty1):
            tx = b.origin_tx + b.width_tiles // 2
            ty = b.origin_ty + b.height_tiles // 2
            ents = _get_entities(sim)
            v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
            return None

        produced = b.tick_farm()
        farm_mult = sim.weather.farm_mult if hasattr(sim, "weather") else 1.0
        if produced and produced > 0:
            actual = max(1, int(produced * farm_mult))
            sim.global_resources["food"] = sim.global_resources.get("food", 0) + actual
            sim.stats["food_produced"] = sim.stats.get("food_produced", 0) + actual

        if v.hunger > 60 or v.energy < 30:
            return "eat" if v.hunger > 60 and sim.global_resources.get("food", 0) > 0 else "rest"
        return None

    def exit(self, v: Villager) -> None:
        pass


class EatState(State):
    """Go to town hall and eat from the global food supply."""

    @property
    def name(self) -> str:
        return "eat"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None or sim.entities.town_hall() is None:
            v._timer = -1
            return
        th = sim.entities.town_hall()
        tx = th.origin_tx + th.width_tiles // 2
        ty = th.origin_ty + th.height_tiles // 2
        ents = _get_entities(sim)
        v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
        v._timer = 0

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        if v._timer == -1:
            return "idle"
        move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
        if v.has_path():
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 1
            return None

        if v._timer == 1:
            food = sim.global_resources.get("food", 0)
            if food > 0 and v.hunger > 10:
                sim.global_resources["food"] = food - 1
                v.hunger = max(0.0, v.hunger - v.hunger_eat_amount)
                # Eating also heals a bit
                v.hp = min(v.max_hp, v.hp + 2)
            v._timer = 0
            return "idle"
        return None

    def exit(self, v: Villager) -> None:
        pass


class GuardState(State):
    """Patrol near town hall, attack enemies on sight."""

    @property
    def name(self) -> str:
        return "guard"

    def enter(self, v: Villager) -> None:
        v.is_guard = True
        v._timer = random.randint(10, 30)

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1

        from enemy import Enemy

        # Look for enemies to fight
        nearest_enemy = None
        nearest_dist = float("inf")
        for e in sim.entities.all():
            if isinstance(e, Enemy) and e.alive:
                d = math.hypot(e.x - v.x, e.y - v.y)
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_enemy = e

        if nearest_enemy is not None:
            if nearest_dist < 1.5 * TILE_SIZE:
                # In melee range — attack
                v.try_attack_enemy(nearest_enemy, sim)
                return None
            else:
                # Chase enemy
                if not v.has_path() or (
                    v.path and (
                        abs(v.path[-1][0] - nearest_enemy.tile_x) > 3
                        or abs(v.path[-1][1] - nearest_enemy.tile_y) > 3
                    )
                ):
                    v._timer -= 1
                    if v._timer <= 0:
                        ents = _get_entities(sim)
                        v.set_path(find_path(
                            (v.tile_x, v.tile_y),
                            (nearest_enemy.tile_x, nearest_enemy.tile_y),
                            sim.world, entities=ents,
                            max_nodes=300,
                        ))
                        v._timer = 15

                move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
                if v.follow_path_tick(sim.tick_rate, move_mult):
                    pass  # Arrived at old position, will repath
                return None

        # No enemies — patrol near town hall
        v._timer -= 1
        if v._timer <= 0 and not v.has_path():
            th = sim.entities.town_hall()
            if th:
                patrol_r = 8
                angle = random.uniform(0, 2 * math.pi)
                tx = max(0, min(
                    int(th.origin_tx + th.width_tiles // 2 + patrol_r * math.cos(angle)),
                    WORLD_W - 1,
                ))
                ty = max(0, min(
                    int(th.origin_ty + th.height_tiles // 2 + patrol_r * math.sin(angle)),
                    WORLD_H - 1,
                ))
                ents = _get_entities(sim)
                if is_walkable(sim.world, tx, ty, ents):
                    v.set_path(find_path(
                        (v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents
                    ))
            v._timer = random.randint(15, 40)

        if v.has_path():
            move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
            v.follow_path_tick(sim.tick_rate, move_mult)

        # Still do critical checks (rest/hunger) but with higher threshold
        if v.energy < 5:
            return "rest"
        if v.hunger > 95 and sim.global_resources.get("food", 0) > 0:
            return "eat"

        return None

    def exit(self, v: Villager) -> None:
        # Keep is_guard = True so they return to guard duty from idle
        pass


class FleeState(State):
    """Run away from nearby enemies."""

    @property
    def name(self) -> str:
        return "flee"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        v._timer = random.randint(10, 25)
        # Calculate flee direction (away from nearest enemy)
        from enemy import Enemy
        nearest = None
        nd = float("inf")
        for e in sim.entities.all():
            if isinstance(e, Enemy) and e.alive:
                d = math.hypot(e.x - v.x, e.y - v.y)
                if d < nd:
                    nd = d
                    nearest = e
        if nearest:
            # Flee in opposite direction
            dx = v.x - nearest.x
            dy = v.y - nearest.y
            dist = math.hypot(dx, dy)
            if dist > 0:
                dx /= dist
                dy /= dist
            flee_dist = random.uniform(8, 16)
            tx = max(0, min(int(v.tile_x + dx * flee_dist), WORLD_W - 1))
            ty = max(0, min(int(v.tile_y + dy * flee_dist), WORLD_H - 1))
            ents = _get_entities(sim)
            if is_walkable(sim.world, tx, ty, ents):
                v.set_path(find_path(
                    (v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents
                ))

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        v._timer -= 1

        # If no more enemies nearby, calm down
        from enemy import Enemy
        threat = False
        for e in sim.entities.all():
            if isinstance(e, Enemy) and e.alive:
                if math.hypot(e.x - v.x, e.y - v.y) < 6 * TILE_SIZE:
                    threat = True
                    break

        if not threat or v._timer <= 0:
            crit = _check_critical(v, sim)
            if crit:
                return crit
            return "idle"

        move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
        # Flee faster (1.3x)
        if v.has_path():
            v.follow_path_tick(sim.tick_rate, move_mult * 1.3)
        return None

    def exit(self, v: Villager) -> None:
        pass


class ResearchState(State):
    """Walk to a library and contribute to active research."""

    @property
    def name(self) -> str:
        return "research"

    def enter(self, v: Villager) -> None:
        sim = v._sim
        if sim is None:
            v._timer = -1
            return
        # Find nearest library
        from config import BuildingType
        libs = [b for b in sim.entities.buildings()
                if b.btype == BuildingType.LIBRARY and b.built and b.alive]
        if not libs:
            v._timer = -1
            return
        best = min(libs, key=lambda b: abs(b.origin_tx - v.tile_x) + abs(b.origin_ty - v.tile_y))
        tx = best.origin_tx + best.width_tiles // 2
        ty = best.origin_ty + best.height_tiles // 2
        ents = _get_entities(sim)
        v.set_path(find_path((v.tile_x, v.tile_y), (tx, ty), sim.world, entities=ents))
        v._timer = 0

    def tick(self, v: Villager, sim: "SimulationManager") -> Optional[str]:
        v.tick_needs(sim)
        if v._attack_cd > 0:
            v._attack_cd -= 1
        if v._timer == -1:
            return "idle"
        threat = _check_enemy_threat(v, sim)
        if threat:
            return threat
        crit = _check_critical(v, sim)
        if crit:
            return crit

        if v.has_path():
            move_mult = sim.weather.move_mult if hasattr(sim, "weather") else 1.0
            if v.follow_path_tick(sim.tick_rate, move_mult):
                v._timer = 0
            return None

        # At library — research ticks are handled by ResearchManager.tick()
        # Just need to be near the library; research system counts scholars
        # Stay here until no more research or needs are low
        if not hasattr(sim, 'research') or sim.research.current_research is None:
            if v.role == Role.SCHOLAR and sim.research.available_techs():
                return "idle"  # Go back to idle to potentially trigger new research start
            return "idle"

        if v.hunger > 70 or v.energy < 25:
            return "eat" if v.hunger > 70 and sim.global_resources.get("food", 0) > 0 else "rest"
        return None

    def exit(self, v: Villager) -> None:
        pass


# ════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════
def _find_nearest_forest(
    v: Villager, sim: "SimulationManager", radius: int = 12
) -> Optional[Tuple[int, int]]:
    best, best_d = None, float("inf")
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tx, ty = v.tile_x + dx, v.tile_y + dy
            if 0 <= tx < WORLD_W and 0 <= ty < WORLD_H:
                if (sim.world.get(tx, ty) == TileType.FOREST
                        and sim.resource_map[ty, tx] > 0):
                    d = abs(dx) + abs(dy)
                    if d < best_d:
                        best_d = d
                        best = (tx, ty)
    return best


def _find_nearest_mountain(
    v: Villager, sim: "SimulationManager", radius: int = 12
) -> Optional[Tuple[int, int]]:
    best, best_d = None, float("inf")
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tx, ty = v.tile_x + dx, v.tile_y + dy
            if 0 <= tx < WORLD_W and 0 <= ty < WORLD_H:
                if sim.world.get(tx, ty) == TileType.MOUNTAIN:
                    d = abs(dx) + abs(dy)
                    if d < best_d:
                        best_d = d
                        best = (tx, ty)
    return best


def _find_any_walkable(
    v: Villager, sim: "SimulationManager", radius: int = 8
) -> List[Tuple[int, int]]:
    ents = _get_entities(sim)
    for r in range(1, radius + 1):
        candidates = []
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                tx, ty = v.tile_x + dx, v.tile_y + dy
                if is_walkable(sim.world, tx, ty, ents):
                    candidates.append((tx, ty))
        if candidates:
            t = random.choice(candidates)
            return [(v.tile_x, v.tile_y), t]
    return [(v.tile_x, v.tile_y)]


# ════════════════════════════════════════════════
#  Renderer
# ════════════════════════════════════════════════
STATE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "idle":           (150, 180, 220),
    "wander":         (120, 200, 120),
    "gather":         (220, 150, 80),
    "mine":           (180, 160, 140),
    "rest":           (180, 130, 220),
    "return_to_base": (220, 200, 80),
    "build":          (200, 180, 140),
    "farm_work":      (100, 200, 80),
    "eat":            (220, 120, 120),
    "guard":          (80, 140, 255),
    "flee":           (255, 200, 100),
    "research":       (180, 130, 255),
}

STATE_LABELS: Dict[str, str] = {
    "idle": "Idle",
    "wander": "Wander",
    "gather": "Gather",
    "mine": "Mining",
    "rest": "Rest",
    "return_to_base": "Returning",
    "build": "Building",
    "farm_work": "Farming",
    "eat": "Eating",
    "guard": "Guarding",
    "flee": "Fleeing",
    "research": "Researching",
}


def draw_villagers(
    surface: pygame.Surface,
    entities,
    camera,
    tick_frac: float,
    font: pygame.font.Font,
    building_hp: dict,
) -> None:
    """Draw every building and villager."""
    zoom = camera.zoom

    # ── Buildings ────────────────────────────────
    for b in entities.buildings():
        sx, sy = camera.world_to_screen(
            b.origin_tx * TILE_SIZE, b.origin_ty * TILE_SIZE
        )
        bw = b.width_tiles * TILE_SIZE * zoom
        bh = b.height_tiles * TILE_SIZE * zoom

        alpha = 255 if b.built else 140
        body_surf = pygame.Surface((int(bw), int(bh)), pygame.SRCALPHA)
        col = (*b.color, alpha)
        pygame.draw.rect(body_surf, col, (0, 0, int(bw), int(bh)), border_radius=3)

        if b.built:
            roof = tuple(max(0, c - 40) for c in b.color)
            pygame.draw.rect(body_surf, (*roof, alpha),
                             (0, 0, int(bw), int(bh * 0.35)), border_radius=3)

        border_col = (80, 60, 30, alpha)
        pygame.draw.rect(body_surf, border_col,
                         (0, 0, int(bw), int(bh)), 2, border_radius=3)
        surface.blit(body_surf, (sx, sy))

        # Wall: crenellation pattern
        if b.btype == BuildingType.WALL and b.built:
            cren_size = max(2, int(4 * zoom))
            cren_col = (90, 90, 95)
            for cx_off in range(0, int(bw), cren_size * 2):
                pygame.draw.rect(surface, cren_col,
                                 (sx + cx_off, sy - cren_size * 0.5, cren_size, cren_size))

        # Gate: door lines
        if b.btype == BuildingType.GATE and b.built:
            gc = (80, 60, 30)
            mid_x = sx + bw * 0.5
            pygame.draw.line(surface, gc, (mid_x, sy), (mid_x, sy + bh), 2)
            pygame.draw.line(surface, gc, (mid_x - bw * 0.2, sy + bh), (mid_x + bw * 0.2, sy + bh), 2)

        # Farm: green crop lines
        if b.btype == BuildingType.FARM and b.built:
            for i in range(1, b.width_tiles):
                lx = sx + i * TILE_SIZE * zoom
                pygame.draw.line(surface, (60, 140, 30),
                                 (lx, sy + 2), (lx, sy + bh - 2), 1)

        # Flag (only on completed non-wall/gate buildings)
        if b.built and b.btype not in (BuildingType.WALL, BuildingType.GATE):
            fx = sx + bw * 0.5
            fy = sy
            pygame.draw.line(surface, (60, 40, 20),
                             (fx, fy), (fx, fy - 12 * zoom), 2)
            flag_col = (200, 50, 50) if b.btype == BuildingType.TOWN_HALL else (80, 160, 80)
            # Phase 6: Gold flag for upgraded buildings
            if b.level > 1:
                flag_col = (255, 215, 0)
            pygame.draw.polygon(surface, flag_col, [
                (fx, fy - 12 * zoom),
                (fx + 10 * zoom, fy - 8 * zoom),
                (fx, fy - 4 * zoom),
            ])
            # Level stars for high-level buildings
            if b.level >= 2 and zoom > 0.5:
                star_y = fy - 14 * zoom
                for i in range(b.level - 1):
                    star_x = fx - (b.level - 2) * 5 * zoom + i * 10 * zoom
                    pygame.draw.circle(surface, (255, 215, 0),
                                       (int(star_x), int(star_y)), max(2, int(3 * zoom)))

        # Building HP bar (when damaged)
        if b.built:
            max_hp = b.defn.get("hp", 100)
            cur_hp = building_hp.get(b.id, max_hp)
            if cur_hp < max_hp:
                bar_w = bw * 0.8
                bar_h = max(3, 4 * zoom)
                bar_x = sx + (bw - bar_w) * 0.5
                bar_y = sy - 8 * zoom
                pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
                fill = bar_w * (cur_hp / max_hp)
                hp_frac = cur_hp / max_hp
                hp_col = (int(220 * (1 - hp_frac)), int(220 * hp_frac), 30)
                pygame.draw.rect(surface, hp_col, (bar_x, bar_y, fill, bar_h))

        # Construction progress bar
        if not b.built:
            bar_w = bw * 0.8
            bar_h = max(3, 4 * zoom)
            bar_x = sx + (bw - bar_w) * 0.5
            bar_y = sy + bh + 4 * zoom
            pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
            fill = bar_w * b.construction_progress
            pygame.draw.rect(surface, (255, 200, 60), (bar_x, bar_y, fill, bar_h))

        # Label
        if zoom > 0.5 and b.btype not in (BuildingType.WALL,):
            label = b.display_name
            if not b.built:
                label += f" ({int(b.construction_progress * 100)}%)"
            elif b.level > 1:
                label += f" Lv.{b.level}"
            lbl = font.render(label, True, (255, 255, 255))
            surface.blit(lbl, (sx + bw * 0.5 - lbl.get_width() * 0.5,
                               sy - 18 * zoom))

        # Upgrade progress bar
        if b.built and b.upgrading:
            bar_w = bw * 0.8
            bar_h = max(3, 4 * zoom)
            bar_x = sx + (bw - bar_w) * 0.5
            bar_y = sy + bh + 4 * zoom
            pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
            fill = bw * b.upgrade_progress
            pygame.draw.rect(surface, (100, 255, 200), (bar_x, bar_y, fill, bar_h))
            # "UPGRADING" label
            if zoom > 0.6:
                ul = font.render(f"UP {int(b.upgrade_progress * 100)}%", True, (100, 255, 200))
                surface.blit(ul, (bar_x, bar_y + bar_h + 1))

    # ── Villagers ────────────────────────────────
    for e in entities.all():
        if isinstance(e, Building) or not e.alive:
            continue
        v: Villager = e

        vx, vy = v.visual_pos(tick_frac)
        sx, sy = camera.world_to_screen(vx, vy)

        r = max(5, int(7 * zoom))
        hr = max(3, int(4 * zoom))

        state_col = STATE_COLORS.get(
            v.fsm.current_state if v.fsm else "idle", (150, 150, 150)
        )

        # Shadow
        shadow = pygame.Surface((r * 3, r), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 50), shadow.get_rect())
        surface.blit(shadow, (sx - r * 1.5, sy + r * 0.3))

        # Body
        pygame.draw.circle(surface, state_col, (int(sx), int(sy)), r)
        outline = tuple(max(0, c - 50) for c in state_col)
        pygame.draw.circle(surface, outline, (int(sx), int(sy)), r, 1)

        # Head
        head_y = sy - r - hr * 0.6
        head_col = tuple(min(255, c + 30) for c in state_col)
        pygame.draw.circle(surface, head_col, (int(sx), int(head_y)), hr)

        # Guard shield icon
        if v.is_guard and zoom > 0.6:
            shield_r = max(2, int(3 * zoom))
            pygame.draw.circle(surface, (60, 100, 200), (int(sx + r), int(sy)), shield_r)

        # Direction triangle
        if v.has_path() and zoom > 0.4:
            dx = math.cos(v.facing) * r * 1.5
            dy = math.sin(v.facing) * r * 1.5
            tip = (sx + dx, sy + dy)
            left = (sx + math.cos(v.facing + 2.5) * r * 0.8,
                    sy + math.sin(v.facing + 2.5) * r * 0.8)
            right = (sx + math.cos(v.facing - 2.5) * r * 0.8,
                     sy + math.sin(v.facing - 2.5) * r * 0.8)
            pygame.draw.polygon(surface, (255, 255, 255), [tip, left, right])

        # Selection ring
        if v.selected:
            pygame.draw.circle(surface, (255, 255, 255),
                               (int(sx), int(sy)), r + 3, 2)

        # HP bar (red, above head)
        if zoom > 0.7:
            bar_w = r * 2.5
            bar_h = max(2, int(3 * zoom))
            bar_x = sx - bar_w * 0.5
            bar_y = head_y - hr - bar_h - 4

            # HP
            pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
            fill_hp = bar_w * (v.hp / v.max_hp)
            hp_frac = v.hp / v.max_hp
            hp_col = (int(220 * (1 - hp_frac)), int(220 * hp_frac), 30)
            pygame.draw.rect(surface, hp_col, (bar_x, bar_y, fill_hp, bar_h))

            # Energy bar (green, below HP)
            bar_y2 = bar_y + bar_h + 1
            pygame.draw.rect(surface, (40, 40, 40),
                             (bar_x, bar_y2, bar_w, bar_h))
            fill = bar_w * (v.energy / v.max_energy)
            ecol = (
                int(220 * (1 - v.energy / v.max_energy)),
                int(220 * (v.energy / v.max_energy)),
                40,
            )
            pygame.draw.rect(surface, ecol, (bar_x, bar_y2, fill, bar_h))

            # Hunger bar (orange, below energy)
            bar_y3 = bar_y2 + bar_h + 1
            pygame.draw.rect(surface, (40, 40, 40),
                             (bar_x, bar_y3, bar_w, bar_h))
            fill2 = bar_w * (v.hunger / v.max_hunger)
            hcol = (220, 140, 40)
            pygame.draw.rect(surface, hcol, (bar_x, bar_y3, fill2, bar_h))

        # Name + state label
        if zoom > 1.0 or v.selected:
            label = v.name
            if v.selected:
                sl = STATE_LABELS.get(v.fsm.current_state if v.fsm else "", "")
                if sl:
                    label += f" [{sl}]"
                carry = v.carry_count()
                if carry > 0:
                    inv_str = " ".join(f"{v2}{k[0]}" for k, v2 in v.inventory.items() if v2 > 0)
                    label += f" {inv_str}"
                label += f" HP:{v.hp}"
            lbl_surf = font.render(label, True, (255, 255, 255))
            surface.blit(lbl_surf, (sx - lbl_surf.get_width() * 0.5,
                                    sy - r - hr * 2 - 16))