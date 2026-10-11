"""
buildings_upgrade.py — Building upgrade system.

Certain building types can be upgraded (max level 3) to improve their
stats: farms produce more food, houses add more pop cap, storage
increases capacity, walls gain more HP, town hall provides more base pop.

Upgrade costs scale with level.  The upgrade is performed by a builder-
role villager (same FSM as construction but targeting an existing building).

Usage:
    Press U on a selected completed building to start an upgrade.
    Builders will path to it and add upgrade ticks automatically.
"""

from __future__ import annotations

from typing import Dict, TYPE_CHECKING

from config import BuildingType, BUILDING_DEFS

if TYPE_CHECKING:
    from simulation import SimulationManager


# ──────────────────────────────────────────────
#  Which buildings can be upgraded and their
#  per-level stat multipliers
# ──────────────────────────────────────────────
UPGRADEABLE: set = {
    BuildingType.FARM,
    BuildingType.HOUSE,
    BuildingType.STORAGE,
    BuildingType.WALL,
    BuildingType.TOWN_HALL,
    BuildingType.LIBRARY,
    BuildingType.TRADING_POST,
}

# How much each stat changes per level (multiplicative or additive)
# "mult_*" keys multiply the base value; "add_*" keys add to it
UPGRADE_BONUSES: Dict[BuildingType, dict] = {
    BuildingType.FARM: {
        2: {"mult_food_rate": 1.8, "mult_food_cycle": 0.75},
        3: {"mult_food_rate": 3.0, "mult_food_cycle": 0.6},
    },
    BuildingType.HOUSE: {
        2: {"add_pop_cap": 2},
        3: {"add_pop_cap": 5},
    },
    BuildingType.STORAGE: {
        2: {"add_hp": 50},
        3: {"add_hp": 100},
    },
    BuildingType.WALL: {
        2: {"add_hp": 100, "name_suffix": " (Stone)"},
        3: {"add_hp": 200, "name_suffix": " (Fortified)"},
    },
    BuildingType.TOWN_HALL: {
        2: {"add_pop_cap": 2, "add_hp": 100},
        3: {"add_pop_cap": 4, "add_hp": 200},
    },
    BuildingType.LIBRARY: {
        2: {"add_hp": 40},
        3: {"add_hp": 80},
    },
    BuildingType.TRADING_POST: {
        2: {"add_hp": 50},
        3: {"add_hp": 100},
    },
}

# Upgrade costs per building type per target level
# Level 2 cost, Level 3 cost
UPGRADE_COSTS: Dict[BuildingType, dict] = {
    BuildingType.FARM: {
        2: {"wood": 5, "stone": 2},
        3: {"wood": 10, "stone": 5, "iron": 2},
    },
    BuildingType.HOUSE: {
        2: {"wood": 8, "stone": 3},
        3: {"wood": 15, "stone": 8},
    },
    BuildingType.STORAGE: {
        2: {"wood": 10, "stone": 5},
        3: {"wood": 20, "stone": 10},
    },
    BuildingType.WALL: {
        2: {"stone": 3},
        3: {"stone": 6, "iron": 2},
    },
    BuildingType.TOWN_HALL: {
        2: {"wood": 15, "stone": 10},
        3: {"wood": 25, "stone": 15, "iron": 5},
    },
    BuildingType.LIBRARY: {
        2: {"wood": 12, "stone": 6},
        3: {"wood": 20, "stone": 10},
    },
    BuildingType.TRADING_POST: {
        2: {"wood": 15, "stone": 8},
        3: {"wood": 25, "stone": 12},
    },
}

MAX_LEVEL: int = 3

# Ticks needed to upgrade (sum of cost values * 3)
def upgrade_ticks_needed(btype: BuildingType, target_level: int) -> int:
    cost = UPGRADE_COSTS.get(btype, {}).get(target_level, {})
    return max(10, sum(cost.values()) * 3)


def get_upgrade_cost(btype: BuildingType, target_level: int) -> dict:
    return dict(UPGRADE_COSTS.get(btype, {}).get(target_level, {}))


def can_upgrade(building, sim: "SimulationManager") -> bool:
    """Check if a building can be upgraded right now."""
    if not building.built or not building.alive:
        return False
    if building.btype not in UPGRADEABLE:
        return False
    level = getattr(building, "level", 1)
    if level >= MAX_LEVEL:
        return False
    target = level + 1
    cost = get_upgrade_cost(building.btype, target)
    for res, amt in cost.items():
        if sim.global_resources.get(res, 0) < amt:
            return False
    # Check not already upgrading
    if getattr(building, "upgrading", False):
        return False
    return True


def start_upgrade(building, sim: "SimulationManager") -> str | None:
    """Start an upgrade. Returns error message or None on success."""
    if not can_upgrade(building, sim):
        return "Cannot upgrade this building."

    level = getattr(building, "level", 1)
    target = level + 1
    cost = get_upgrade_cost(building.btype, target)

    # Deduct cost
    for res, amt in cost.items():
        sim.global_resources[res] = sim.global_resources.get(res, 0) - amt

    building.level = target
    building.upgrading = True
    building.upgrade_progress = 0.0
    building.upgrade_ticks = upgrade_ticks_needed(building.btype, target)

    cost_str = " ".join(f"{v}{k[0]}" for k, v in cost.items())
    sim.event_log.add(
        f"Upgrading {building.name} to Lv.{target} (cost: {cost_str})",
        (200, 200, 100),
    )
    return None


def apply_upgrade_effects(building, sim: "SimulationManager") -> None:
    """Apply stat changes when an upgrade completes."""
    level = getattr(building, "level", 1)
    bonuses = UPGRADE_BONUSES.get(building.btype, {}).get(level, {})

    # Update building stats
    defn = building.defn

    if "add_pop_cap" in bonuses:
        # We track extra pop cap from upgrades on the building
        building.extra_pop_cap = getattr(building, "extra_pop_cap", 0) + bonuses["add_pop_cap"]

    if "add_hp" in bonuses:
        old_hp = sim.building_hp.get(building.id, defn.get("hp", 100))
        sim.building_hp[building.id] = old_hp + bonuses["add_hp"]

    if "mult_food_rate" in bonuses:
        building.food_rate_mult = getattr(building, "food_rate_mult", 1.0) * bonuses["mult_food_rate"]

    if "mult_food_cycle" in bonuses:
        building.food_cycle_mult = getattr(building, "food_cycle_mult", 1.0) * bonuses["mult_food_cycle"]

    if "name_suffix" in bonuses:
        building.display_name = defn["name"] + bonuses["name_suffix"]

    building.upgrading = False
    sim.event_log.add(
        f"{building.display_name} upgraded to Lv.{level}!",
        (100, 255, 200),
    )
    sim.stats["buildings_upgraded"] = sim.stats.get("buildings_upgraded", 0) + 1


def add_upgrade_tick(building) -> bool:
    """Advance upgrade by 1 tick. Returns True when complete."""
    if not getattr(building, "upgrading", False):
        return True
    needed = getattr(building, "upgrade_ticks", 10)
    building.upgrade_progress = getattr(building, "upgrade_progress", 0.0) + 1.0 / needed
    if building.upgrade_progress >= 0.999:
        building.upgrade_progress = 1.0
        return True
    return False


def get_effective_pop_cap(building) -> int:
    """Get pop cap including upgrade bonuses."""
    base = building.defn.get("pop_cap", 0) if building.built else 0
    extra = getattr(building, "extra_pop_cap", 0)
    return base + extra


def get_effective_food_rate(building) -> tuple:
    """Get (food_rate, food_cycle) with upgrade multipliers applied."""
    defn = building.defn
    rate = defn.get("food_rate", 0)
    cycle = defn.get("food_cycle", 0)
    rate_mult = getattr(building, "food_rate_mult", 1.0)
    cycle_mult = getattr(building, "food_cycle_mult", 1.0)
    return rate * rate_mult, max(1, int(cycle * cycle_mult))