"""
config.py — Shared constants and types for all modules.
"""

from enum import IntEnum, auto

TILE_SIZE: int = 32
WORLD_W: int = 256
WORLD_H: int = 256

# ──────────────────────────────────────────────
# Tile type palette
# ──────────────────────────────────────────────
class TileType(IntEnum):
    GRASS    = 0
    WATER    = auto()
    SAND     = auto()
    FOREST   = auto()
    MOUNTAIN = auto()
    LAVA     = auto()

# (base R, G, B, name)
TILE_PALETTE = {
    TileType.GRASS:    (( 72, 160,  72), "Grass"),
    TileType.WATER:    (( 50, 120, 210), "Water"),
    TileType.SAND:     ((210, 190, 130), "Sand"),
    TileType.FOREST:   (( 34, 110,  44), "Forest"),
    TileType.MOUNTAIN: ((140, 140, 140), "Mountain"),
    TileType.LAVA:     ((210,  60,  20), "Lava"),
}

WALKABLE_TILES = {TileType.GRASS, TileType.SAND, TileType.FOREST, TileType.MOUNTAIN}

SAVE_PATH = "world_save.npz"


# ──────────────────────────────────────────────
# Building types
# ──────────────────────────────────────────────
class BuildingType(IntEnum):
    TOWN_HALL  = 0
    HOUSE      = auto()
    FARM       = auto()
    STORAGE    = auto()
    WALL       = auto()
    GATE       = auto()
    LIBRARY    = auto()
    TRADING_POST = auto()
    EMBASSY    = auto()


# (name, width, height, color, cost_dict, pop_cap_bonus, food_per_cycle, cycle_ticks)
#   food_per_cycle / cycle_ticks: farm produces this much food every N ticks
BUILDING_DEFS = {
    BuildingType.TOWN_HALL: {
        "name": "Town Hall",  "w": 2, "h": 2,
        "color": (160, 120, 60),
        "cost": {},
        "pop_cap": 4,  "food_rate": 0,  "food_cycle": 0,
        "hp": 200,
    },
    BuildingType.HOUSE: {
        "name": "House",  "w": 2, "h": 2,
        "color": (140, 100, 55),
        "cost": {"wood": 5},
        "pop_cap": 3,  "food_rate": 0,  "food_cycle": 0,
        "hp": 80,
    },
    BuildingType.FARM: {
        "name": "Farm",  "w": 2, "h": 1,
        "color": (120, 160, 60),
        "cost": {"wood": 3},
        "pop_cap": 0,  "food_rate": 1,  "food_cycle": 30,
        "hp": 40,
    },
    BuildingType.STORAGE: {
        "name": "Storage",  "w": 2, "h": 2,
        "color": (130, 95, 45),
        "cost": {"wood": 8},
        "pop_cap": 0,  "food_rate": 0,  "food_cycle": 0,
        "hp": 100,
    },
    BuildingType.WALL: {
        "name": "Wall",  "w": 1, "h": 1,
        "color": (110, 110, 115),
        "cost": {"stone": 2},
        "pop_cap": 0,  "food_rate": 0,  "food_cycle": 0,
        "hp": 150,
        "blocks_movement": True,
    },
    BuildingType.GATE: {
        "name": "Gate",  "w": 1, "h": 1,
        "color": (130, 100, 60),
        "cost": {"wood": 3, "stone": 2},
        "pop_cap": 0,  "food_rate": 0,  "food_cycle": 0,
        "hp": 120,
        "blocks_movement": False,
    },
    BuildingType.LIBRARY: {
        "name": "Library",  "w": 2, "h": 2,
        "color": (120, 90, 160),
        "cost": {"wood": 8, "stone": 4},
        "pop_cap": 0,  "food_rate": 0,  "food_cycle": 0,
        "hp": 60,
        "enables_research": True,
    },
    BuildingType.TRADING_POST: {
        "name": "Trading Post",  "w": 2, "h": 2,
        "color": (180, 140, 80),
        "cost": {"wood": 10, "stone": 5},
        "pop_cap": 0,  "food_rate": 0,  "food_cycle": 0,
        "hp": 80,
        "enables_trading": True,
    },
    BuildingType.EMBASSY: {
        "name": "Embassy",  "w": 2, "h": 2,
        "color": (100, 140, 180),
        "cost": {"wood": 15, "stone": 10},
        "pop_cap": 0,  "food_rate": 0,  "food_cycle": 0,
        "hp": 70,
        "enables_diplomacy": True,
    },
}

# Palette-bar order for the build mode buttons
BUILD_BAR_ORDER = [
    BuildingType.HOUSE, BuildingType.FARM, BuildingType.STORAGE,
    BuildingType.WALL, BuildingType.GATE,
    BuildingType.LIBRARY, BuildingType.TRADING_POST,
    BuildingType.EMBASSY,
]


# ──────────────────────────────────────────────
# Day / Night cycle
# ──────────────────────────────────────────────
DAY_LENGTH: float = 120.0        # seconds for one full cycle

# Phase boundaries (fraction of cycle)
DAWN_END: float   = 0.15         # 0 .. 0.15  = dawn
DAY_END: float    = 0.45         # 0.15 .. 0.45 = day
DUSK_END: float   = 0.60         # 0.45 .. 0.60 = dusk
                                # 0.60 .. 1.00 = night


# ──────────────────────────────────────────────
# Weather system
# ──────────────────────────────────────────────
class Weather(IntEnum):
    CLEAR  = 0
    RAIN   = auto()
    STORM  = auto()
    SNOW   = auto()

# How weather affects simulation (multipliers / flags)
WEATHER_EFFECTS = {
    Weather.CLEAR:  {"move_mult": 1.0, "farm_mult": 1.0, "combat_mult": 1.0, "label": "Clear"},
    Weather.RAIN:   {"move_mult": 0.8, "farm_mult": 1.3, "combat_mult": 0.9, "label": "Rain"},
    Weather.STORM:  {"move_mult": 0.6, "farm_mult": 0.5, "combat_mult": 0.7, "label": "Storm"},
    Weather.SNOW:   {"move_mult": 0.7, "farm_mult": 0.2, "combat_mult": 0.8, "label": "Snow"},
}

# Weather transition: min/max ticks per weather phase, and weights for next
WEATHER_MIN_TICKS: int = 50     # ~5s at 10 TPS
WEATHER_MAX_TICKS: int = 300    # ~30s
WEATHER_TRANSITION = {
    # current: [(weather, weight), ...]
    Weather.CLEAR:  [(Weather.CLEAR, 60), (Weather.RAIN, 25), (Weather.STORM, 5), (Weather.SNOW, 10)],
    Weather.RAIN:   [(Weather.RAIN, 40), (Weather.CLEAR, 30), (Weather.STORM, 20), (Weather.SNOW, 10)],
    Weather.STORM:  [(Weather.STORM, 30), (Weather.RAIN, 30), (Weather.CLEAR, 30), (Weather.SNOW, 10)],
    Weather.SNOW:   [(Weather.SNOW, 40), (Weather.CLEAR, 30), (Weather.RAIN, 20), (Weather.STORM, 10)],
}


# ──────────────────────────────────────────────
# Enemy / Combat
# ──────────────────────────────────────────────
ENEMY_SPAWN_MIN_TICKS: int = 200   # ~20s
ENEMY_SPAWN_MAX_TICKS: int = 600   # ~60s
ENEMY_BASE_HEALTH: int = 30
ENEMY_BASE_DAMAGE: int = 5
ENEMY_SPEED: float = 2.0   # tiles/s
ENEMY_ATTACK_RANGE: float = 1.5  # tiles
ENEMY_ATTACK_COOLDOWN: int = 5    # ticks between attacks

RAID_DIFFICULTY_SCALE: float = 1.15  # each raid is 15% harder

# ──────────────────────────────────────────────
# Villager combat
# ──────────────────────────────────────────────
VILLAGER_BASE_HEALTH: int = 50
VILLAGER_BASE_DAMAGE: int = 8
VILLAGER_ATTACK_COOLDOWN: int = 4
GUARD_DAMAGE_BONUS: float = 1.5


# ──────────────────────────────────────────────
# Villager Roles / Specializations
# ──────────────────────────────────────────────
class Role(IntEnum):
    NONE      = 0
    LUMBERJACK = auto()
    MINER     = auto()
    FARMER    = auto()
    GUARD     = auto()
    BUILDER   = auto()
    SCHOLAR   = auto()

ROLE_NAMES = {
    Role.NONE:      "Villager",
    Role.LUMBERJACK: "Lumberjack",
    Role.MINER:     "Miner",
    Role.FARMER:    "Farmer",
    Role.GUARD:     "Guard",
    Role.BUILDER:   "Builder",
    Role.SCHOLAR:   "Scholar",
}

ROLE_COLORS = {
    Role.NONE:      (150, 150, 150),
    Role.LUMBERJACK: (100, 180, 60),
    Role.MINER:     (180, 160, 120),
    Role.FARMER:    (140, 200, 80),
    Role.GUARD:     (80, 140, 255),
    Role.BUILDER:   (200, 180, 100),
    Role.SCHOLAR:   (180, 130, 255),
}

# Efficiency multiplier per role for different tasks
ROLE_EFFICIENCY = {
    "gather_wood":  {Role.LUMBERJACK: 2.0, Role.NONE: 1.0},
    "mine_stone":   {Role.MINER: 2.0, Role.NONE: 1.0},
    "mine_iron":    {Role.MINER: 2.0, Role.NONE: 1.0},
    "farm_work":    {Role.FARMER: 2.0, Role.NONE: 1.0},
    "combat_damage":{Role.GUARD: 1.8, Role.NONE: 1.0},
    "build_speed":  {Role.BUILDER: 2.0, Role.NONE: 1.0},
    "research_speed":{Role.SCHOLAR: 2.0, Role.NONE: 1.0},
}


def role_efficiency(role: Role, task: str) -> float:
    table = ROLE_EFFICIENCY.get(task, {})
    return table.get(role, table.get(Role.NONE, 1.0))


# ──────────────────────────────────────────────
# Research / Technology Tree
# ──────────────────────────────────────────────
class Tech(IntEnum):
    BETTER_TOOLS     = 0   # +50% gather/mine speed
    AGRICULTURE      = auto()  # +100% farm output
    FORTIFICATIONS   = auto()  # +50% wall/building HP
    MEDICINE         = auto()  # +100% healing, +20 max HP
    METALLURGY       = auto()  # unlock iron mining, +50% combat dmg
    ARCHERY          = auto()  # +1 tile attack range
    STORAGE_MASTER   = auto()  # +50% carry capacity
    TRADE_ROUTES     = auto()  # better trade deals

TECH_DEFS = {
    Tech.BETTER_TOOLS: {
        "name": "Better Tools",
        "desc": "+50% resource gathering",
        "cost": {"food": 15, "stone": 5},
        "requires": [],
        "research_ticks": 80,
        "effect": "gather_bonus",
    },
    Tech.AGRICULTURE: {
        "name": "Agriculture",
        "desc": "Double farm output",
        "cost": {"food": 20, "wood": 10},
        "requires": [],
        "research_ticks": 100,
        "effect": "farm_bonus",
    },
    Tech.FORTIFICATIONS: {
        "name": "Fortifications",
        "desc": "+50% building HP",
        "cost": {"stone": 15, "wood": 10},
        "requires": [Tech.BETTER_TOOLS],
        "research_ticks": 120,
        "effect": "fortify_bonus",
    },
    Tech.MEDICINE: {
        "name": "Medicine",
        "desc": "+20 HP, faster healing",
        "cost": {"food": 25, "stone": 5},
        "requires": [Tech.AGRICULTURE],
        "research_ticks": 100,
        "effect": "medicine_bonus",
    },
    Tech.METALLURGY: {
        "name": "Metallurgy",
        "desc": "Unlock iron, +50% damage",
        "cost": {"stone": 20, "food": 15},
        "requires": [Tech.BETTER_TOOLS],
        "research_ticks": 150,
        "effect": "metallurgy_bonus",
    },
    Tech.ARCHERY: {
        "name": "Archery",
        "desc": "+1 tile attack range",
        "cost": {"wood": 15, "stone": 10, "food": 10},
        "requires": [Tech.METALLURGY],
        "research_ticks": 130,
        "effect": "range_bonus",
    },
    Tech.STORAGE_MASTER: {
        "name": "Storage Mastery",
        "desc": "+50% carry capacity",
        "cost": {"wood": 15, "stone": 8},
        "requires": [Tech.BETTER_TOOLS],
        "research_ticks": 80,
        "effect": "carry_bonus",
    },
    Tech.TRADE_ROUTES: {
        "name": "Trade Routes",
        "desc": "Better trade deals",
        "cost": {"food": 20, "wood": 15, "stone": 10},
        "requires": [Tech.AGRICULTURE],
        "research_ticks": 120,
        "effect": "trade_bonus",
    },
}


# ──────────────────────────────────────────────
# Trading
# ──────────────────────────────────────────────
TRADE_MIN_TICKS: int = 300   # ~30s between merchants
TRADE_MAX_TICKS: int = 600   # ~60s
MERCHANT_STAY_TICKS: int = 60  # merchant stays 6s

# Trade offers: (give_resource, give_amount, receive_resource, receive_amount)
TRADE_OFFERS = [
    {"give": ("food", 10),  "receive": ("wood", 8)},
    {"give": ("wood", 10), "receive": ("stone", 6)},
    {"give": ("stone", 8),  "receive": ("food", 12)},
    {"give": ("food", 15), "receive": ("stone", 8)},
    {"give": ("wood", 8),   "receive": ("food", 10)},
]


# ──────────────────────────────────────────────
# Diplomacy
# ──────────────────────────────────────────────
DIPLO_EVENT_MIN_TICKS: int = 400   # ~40s between AI village events
DIPLO_EVENT_MAX_TICKS: int = 800   # ~80s
DIPLO_MAX_VILLAGES: int = 4
DIPLO_VILLAGE_NAMES = [
    "Ironhold", "Silverdale", "Thornwall", "Ashford",
    "Ravencrest", "Goldmere", "Stormwatch", "Duskholm",
]
DIPLO_PERSONALITIES = ["aggressive", "peaceful", "trading", "isolationist"]

# Relationship thresholds
RELATION_ALLY: int = 70
RELATION_FRIENDLY: int = 30
RELATION_NEUTRAL_LOW: int = -30
RELATION_HOSTILE: int = -60

# Relationship change values
GIFT_RELATION_BONUS: int = 12
TRADE_PACT_BONUS: int = 8
ALLIANCE_BONUS: int = 15
TRIBUTE_FAIL_PENALTY: int = -20
WAR_DECLARE_PENALTY: int = -50
PEACE_PROPOSAL_BONUS: int = 10