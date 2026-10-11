"""
entities.py — Entity base class, Building (with construction), and
EntityManager.
"""

from __future__ import annotations

import math
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING

from config import TILE_SIZE, WORLD_W, WORLD_H, BuildingType, BUILDING_DEFS

if TYPE_CHECKING:
    pass


# ════════════════════════════════════════════════
#  Entity
# ════════════════════════════════════════════════
class Entity:
    """Anything that exists in the world — villagers, buildings, etc."""

    _next_id: int = 0

    def __init__(self, wx: float, wy: float, name: str = "Entity") -> None:
        Entity._next_id += 1
        self.id: int = Entity._next_id
        self.name: str = name
        self.x: float = wx
        self.y: float = wy
        self.prev_x: float = wx
        self.prev_y: float = wy
        self.tile_x: int = int(wx // TILE_SIZE)
        self.tile_y: int = int(wy // TILE_SIZE)
        self.alive: bool = True
        self.selected: bool = False

    def set_position(self, wx: float, wy: float) -> None:
        self.x = wx
        self.y = wy
        self.tile_x = int(wx // TILE_SIZE)
        self.tile_y = int(wy // TILE_SIZE)

    def save_prev(self) -> None:
        self.prev_x = self.x
        self.prev_y = self.y

    def visual_pos(self, frac: float) -> Tuple[float, float]:
        vx = self.prev_x + (self.x - self.prev_x) * frac
        vy = self.prev_y + (self.y - self.prev_y) * frac
        return vx, vy

    def move_toward_tile(self, tx: int, ty: int, step_world: float) -> bool:
        target_wx = tx * TILE_SIZE + TILE_SIZE * 0.5
        target_wy = ty * TILE_SIZE + TILE_SIZE * 0.5
        dx = target_wx - self.x
        dy = target_wy - self.y
        dist = math.hypot(dx, dy)
        if dist <= step_world:
            self.set_position(target_wx, target_wy)
            return True
        self.x += (dx / dist) * step_world
        self.y += (dy / dist) * step_world
        self.tile_x = int(self.x // TILE_SIZE)
        self.tile_y = int(self.y // TILE_SIZE)
        return False


# ════════════════════════════════════════════════
#  Building
# ════════════════════════════════════════════════
class Building(Entity):
    """An immobile structure.  Supports in-progress construction."""

    def __init__(
        self,
        tx: int, ty: int,
        width_tiles: int = 2,
        height_tiles: int = 2,
        name: str = "Building",
        color: Tuple[int, int, int] = (160, 120, 60),
        btype: BuildingType = BuildingType.TOWN_HALL,
        cost: Optional[Dict[str, int]] = None,
    ) -> None:
        wx = tx * TILE_SIZE + width_tiles * TILE_SIZE * 0.5
        wy = ty * TILE_SIZE + height_tiles * TILE_SIZE * 0.5
        super().__init__(wx, wy, name)
        self.origin_tx: int = tx
        self.origin_ty: int = ty
        self.width_tiles: int = width_tiles
        self.height_tiles: int = height_tiles
        self.color: Tuple[int, int, int] = color
        self.btype: BuildingType = btype
        self.cost: Dict[str, int] = cost or {}

        # Construction progress (0.0 – 1.0).  1.0 = complete.
        self.construction_progress: float = 0.0
        self.built: bool = False

        # Farm production timer
        self._farm_timer: int = 0

        # Phase 6: Building upgrade system
        self.level: int = 1
        self.upgrading: bool = False
        self.upgrade_progress: float = 0.0
        self.upgrade_ticks: int = 0
        self.extra_pop_cap: int = 0
        self.food_rate_mult: float = 1.0
        self.food_cycle_mult: float = 1.0
        self.display_name: str = name

    @property
    def defn(self) -> dict:
        return BUILDING_DEFS.get(self.btype, {})

    @property
    def pop_cap(self) -> int:
        base = self.defn.get("pop_cap", 0) if self.built else 0
        return base + self.extra_pop_cap

    @property
    def tile_rect(self) -> Tuple[int, int, int, int]:
        return (
            self.origin_tx, self.origin_ty,
            self.origin_tx + self.width_tiles,
            self.origin_ty + self.height_tiles,
        )

    def construction_ticks_needed(self) -> int:
        """Total ticks to build = sum of cost values * 2."""
        return sum(self.cost.values()) * 2

    def add_construction_tick(self) -> bool:
        """Advance construction by 1 tick.  Returns True when complete."""
        if self.built:
            return True
        needed = self.construction_ticks_needed()
        if needed <= 0:
            self.built = True
            self.construction_progress = 1.0
            return True
        self.construction_progress += 1.0 / needed
        if self.construction_progress >= 1.0:
            self.construction_progress = 1.0
            self.built = True
            return True
        return False

    def tick_farm(self) -> Optional[int]:
        """If this is a completed farm, advance production.

        Returns the amount of food produced this tick, or None.
        """
        if self.btype != BuildingType.FARM or not self.built:
            return None
        cycle = self.defn.get("food_cycle", 0)
        rate = self.defn.get("food_rate", 0)
        if cycle <= 0 or rate <= 0:
            return None
        # Phase 6: Apply upgrade multipliers
        effective_rate = rate * self.food_rate_mult
        effective_cycle = max(1, int(cycle * self.food_cycle_mult))
        self._farm_timer += 1
        if self._farm_timer >= effective_cycle:
            self._farm_timer = 0
            return max(1, int(effective_rate))
        return None


# ════════════════════════════════════════════════
#  EntityManager
# ════════════════════════════════════════════════
class EntityManager:
    """Central registry for all entities."""

    def __init__(self) -> None:
        self._entities: List[Entity] = []

    def add(self, entity: Entity) -> None:
        self._entities.append(entity)

    def remove(self, entity: Entity) -> None:
        entity.alive = False
        if entity in self._entities:
            self._entities.remove(entity)

    def cull_dead(self) -> int:
        before = len(self._entities)
        self._entities = [e for e in self._entities if e.alive]
        return before - len(self._entities)

    def all(self) -> List[Entity]:
        return self._entities

    def villagers(self) -> List[Entity]:
        return [e for e in self._entities if e.alive and not isinstance(e, Building)]

    def buildings(self) -> List[Building]:
        return [e for e in self._entities if isinstance(e, Building) and e.alive]

    def completed_buildings(self) -> List[Building]:
        return [b for b in self.buildings() if b.built]

    def unfinished_buildings(self) -> List[Building]:
        return [b for b in self.buildings() if not b.built]

    def upgrading_buildings(self) -> List[Building]:
        """Buildings that are currently being upgraded."""
        return [b for b in self.buildings() if b.built and getattr(b, "upgrading", False)]

    def farms(self) -> List[Building]:
        from config import BuildingType
        return [b for b in self.completed_buildings()
                if b.btype == BuildingType.FARM]

    def libraries(self) -> List[Building]:
        from config import BuildingType
        return [b for b in self.completed_buildings()
                if b.btype == BuildingType.LIBRARY]

    def trading_posts(self) -> List[Building]:
        from config import BuildingType
        return [b for b in self.completed_buildings()
                if b.btype == BuildingType.TRADING_POST]

    def town_hall(self) -> Optional[Building]:
        for b in self.buildings():
            if b.btype == BuildingType.TOWN_HALL:
                return b
        return None

    def pop_cap(self) -> int:
        return sum(b.pop_cap for b in self.buildings())

    def select_at_tile(self, tx: int, ty: int) -> Optional[Entity]:
        for e in self._entities:
            e.selected = False
        for e in self._entities:
            if e.alive and e.tile_x == tx and e.tile_y == ty and not isinstance(e, Building):
                e.selected = True
                return e
        return None

    def deselect_all(self) -> None:
        for e in self._entities:
            e.selected = False