"""
enemy.py — Enemy (goblin/raider) entity with AI, pathfinding, and combat.

Enemies spawn from map edges during raids, pathfind toward the town hall
or nearest building, and attack villagers and structures on contact.
"""

from __future__ import annotations

import math
import random
from typing import Optional, List, Tuple, TYPE_CHECKING

import pygame

from config import (
    TILE_SIZE, WORLD_W, WORLD_H, TileType,
    ENEMY_BASE_HEALTH, ENEMY_BASE_DAMAGE, ENEMY_SPEED,
    ENEMY_ATTACK_RANGE, ENEMY_ATTACK_COOLDOWN,
    RAID_DIFFICULTY_SCALE,
)
from entities import Entity, Building
from pathfinding import find_path

if TYPE_CHECKING:
    from simulation import SimulationManager


# ════════════════════════════════════════════════
#  Enemy names
# ════════════════════════════════════════════════
GOBLIN_NAMES = [
    "Grik", "Snarl", "Mug", "Fang", "Rot",
    "Skulk", "Grub", "Thorn", "Bile", "Dreg",
    "Gnash", "Vex", "Runt", "Slime", "Scab",
]


# ════════════════════════════════════════════════
#  Enemy entity
# ════════════════════════════════════════════════
class Enemy(Entity):
    """A hostile goblin that attacks the village."""

    _next_id: int = 1000  # separate ID range

    def __init__(self, wx: float, wy: float, raid_number: int = 1) -> None:
        # Use class-level _next_id via Entity's mechanism
        super().__init__(wx, wy, random.choice(GOBLIN_NAMES))
        self.id = Enemy._next_id
        Enemy._next_id += 1

        # Combat stats scale with raid number
        scale = RAID_DIFFICULTY_SCALE ** (raid_number - 1)
        self.max_hp: int = int(ENEMY_BASE_HEALTH * scale)
        self.hp: int = self.max_hp
        self.damage: int = int(ENEMY_BASE_DAMAGE * scale)
        self.speed: float = ENEMY_SPEED
        self.attack_range: float = ENEMY_ATTACK_RANGE
        self.attack_cooldown: int = ENEMY_ATTACK_COOLDOWN
        self._cooldown_timer: int = 0

        # AI
        self.path: List[Tuple[int, int]] = []
        self.facing: float = random.uniform(0, 2 * math.pi)
        self.target: Optional[Entity] = None  # current attack target
        self.raid_number: int = raid_number

    def set_path(self, path: List[Tuple[int, int]]) -> None:
        self.path = list(path)

    def has_path(self) -> bool:
        return len(self.path) > 0

    def follow_path_tick(self, tick_rate: float) -> bool:
        if not self.path:
            return True
        step = self.speed * TILE_SIZE / tick_rate
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

    def take_damage(self, dmg: int) -> bool:
        """Returns True if killed."""
        self.hp -= dmg
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def tick_ai(self, sim: "SimulationManager") -> None:
        """One simulation tick of enemy AI."""
        # Cooldown
        if self._cooldown_timer > 0:
            self._cooldown_timer -= 1

        # Check for attack targets in range
        if self._cooldown_timer <= 0:
            victim = self._find_target(sim)
            if victim is not None:
                self._attack(victim, sim)
                self.target = victim
                return

        # Find a target building to path toward
        target_pos = self._get_target_position(sim)
        if target_pos is None:
            # Wander
            if not self.has_path():
                self._wander(sim)
        else:
            tx, ty = int(target_pos[0]), int(target_pos[1])
            if not self.has_path() or (
                self.path and (self.path[-1][0] != tx or self.path[-1][1] != ty)
            ):
                # Recalculate path periodically
                self.set_path(find_path(
                    (self.tile_x, self.tile_y), (tx, ty), sim.world, max_nodes=400
                ))

        if self.has_path():
            move_mult = getattr(sim.weather, "move_mult", 1.0) if hasattr(sim, "weather") else 1.0
            old_rate = sim.tick_rate
            sim.tick_rate *= move_mult
            self.follow_path_tick(sim.tick_rate)
            sim.tick_rate = old_rate

    def _find_target(self, sim: "SimulationManager") -> Optional[Entity]:
        """Find the nearest attackable entity in range."""
        best, best_d = None, self.attack_range * TILE_SIZE
        for e in sim.entities.all():
            if not e.alive:
                continue
            dx = e.x - self.x
            dy = e.y - self.y
            d = math.hypot(dx, dy)
            if d < best_d:
                best_d = d
                best = e
        return best

    def _attack(self, target: Entity, sim: "SimulationManager") -> None:
        """Deal damage to target."""
        combat_mult = 1.0
        if hasattr(sim, "weather"):
            combat_mult = sim.weather.combat_mult

        dmg = max(1, int(self.damage * combat_mult))
        self._cooldown_timer = self.attack_cooldown
        self.facing = math.atan2(target.y - self.y, target.x - self.x)

        if isinstance(target, Enemy):
            return  # Don't attack other enemies

        if isinstance(target, Building):
            # Damage building
            target_defn = target.defn
            if "hp" in target_defn:
                # We use a simple approach: track building HP via a dict on sim
                bhp = sim.building_hp.get(target.id, target_defn["hp"])
                bhp -= dmg
                sim.building_hp[target.id] = bhp
                if bhp <= 0:
                    target.alive = False
                    sim.event_log.add(
                        f"{target.name} destroyed by {self.name}!",
                        (255, 80, 80),
                    )
                    sim.stats["buildings_destroyed"] = sim.stats.get("buildings_destroyed", 0) + 1
                return

        # Target is a villager
        if hasattr(target, "hp"):
            killed = target.take_damage(dmg)
            if killed:
                sim.event_log.add(
                    f"{target.name} was slain by {self.name}!",
                    (255, 80, 80),
                )
                sim.stats["villagers_lost"] = sim.stats.get("villagers_lost", 0) + 1
                sim.sounds.play("villager_death")
                # Drop carried items
                for res, amt in target.inventory.items():
                    sim.global_resources[res] = sim.global_resources.get(res, 0) + amt
                target.inventory.clear()

    def _get_target_position(self, sim: "SimulationManager") -> Optional[Tuple[float, float]]:
        """Get the position of the priority target (town hall > nearest building)."""
        th = sim.entities.town_hall()
        if th and th.alive:
            return (th.x, th.y)
        buildings = sim.entities.buildings()
        if buildings:
            b = min(buildings, key=lambda b: math.hypot(b.x - self.x, b.y - self.y))
            return (b.x, b.y)
        # Attack villagers directly
        villagers = sim.entities.villagers()
        if villagers:
            v = min(villagers, key=lambda v: math.hypot(v.x - self.x, v.y - self.y))
            return (v.x, v.y)
        return None

    def _wander(self, sim: "SimulationManager") -> None:
        angle = random.uniform(0, 2 * math.pi)
        dist = random.randint(5, 15)
        tx = max(0, min(int(self.tile_x + dist * math.cos(angle)), WORLD_W - 1))
        ty = max(0, min(int(self.tile_y + dist * math.sin(angle)), WORLD_H - 1))
        self.set_path(find_path((self.tile_x, self.tile_y), (tx, ty), sim.world, max_nodes=200))


# ════════════════════════════════════════════════
#  Enemy renderer
# ════════════════════════════════════════════════
def draw_enemies(
    surface: pygame.Surface,
    entities,
    camera,
    tick_frac: float,
    font: pygame.font.Font,
    building_hp: dict,
) -> None:
    """Draw all enemy entities."""
    zoom = camera.zoom

    for e in entities.all():
        if not isinstance(e, Enemy) or not e.alive:
            continue
        enemy: Enemy = e

        vx, vy = enemy.visual_pos(tick_frac)
        sx, sy = camera.world_to_screen(vx, vy)

        r = max(6, int(8 * zoom))

        # Shadow
        shadow = pygame.Surface((r * 3, r), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 50), shadow.get_rect())
        surface.blit(shadow, (sx - r * 1.5, sy + r * 0.3))

        # Body — dark red/green goblin
        body_col = (160, 50, 50) if enemy.hp > enemy.max_hp * 0.3 else (100, 30, 30)
        pygame.draw.circle(surface, body_col, (int(sx), int(sy)), r)
        pygame.draw.circle(surface, (80, 20, 20), (int(sx), int(sy)), r, 1)

        # Eyes (two small yellow dots)
        eye_r = max(1, int(2 * zoom))
        ey = int(sy - r * 0.2)
        pygame.draw.circle(surface, (255, 220, 50), (int(sx - r * 0.3), ey), eye_r)
        pygame.draw.circle(surface, (255, 220, 50), (int(sx + r * 0.3), ey), eye_r)

        # Direction indicator
        if enemy.has_path() and zoom > 0.4:
            dx = math.cos(enemy.facing) * r * 1.3
            dy = math.sin(enemy.facing) * r * 1.3
            pygame.draw.circle(surface, (255, 100, 100),
                               (int(sx + dx), int(sy + dy)), max(2, int(3 * zoom)))

        # HP bar
        if zoom > 0.5:
            bar_w = r * 2.5
            bar_h = max(2, int(3 * zoom))
            bar_x = sx - bar_w * 0.5
            bar_y = sy - r - bar_h - 4
            pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
            fill = bar_w * (enemy.hp / enemy.max_hp)
            hp_frac = enemy.hp / enemy.max_hp
            hp_col = (int(220 * (1 - hp_frac)), int(220 * hp_frac), 30)
            pygame.draw.rect(surface, hp_col, (bar_x, bar_y, fill, bar_h))

        # Name label when zoomed in
        if zoom > 1.2:
            lbl = font.render(f"{enemy.name} (R{enemy.raid_number})", True, (255, 120, 120))
            surface.blit(lbl, (sx - lbl.get_width() * 0.5, sy - r - 20))


def spawn_raid(sim: "SimulationManager", raid_number: int = 1) -> List[Enemy]:
    """Spawn a wave of enemies from map edges."""
    th = sim.entities.town_hall()
    if th is None:
        return []

    # Spawn 2 + raid_number enemies, max 8
    count = min(2 + raid_number, 8)

    # Pick a random edge to spawn from
    edge = random.randint(0, 3)
    enemies: List[Enemy] = []
    for i in range(count):
        if edge == 0:  # top
            tx = random.randint(0, WORLD_W - 1)
            ty = 0
        elif edge == 1:  # bottom
            tx = random.randint(0, WORLD_W - 1)
            ty = WORLD_H - 1
        elif edge == 2:  # left
            tx = 0
            ty = random.randint(0, WORLD_H - 1)
        else:  # right
            tx = WORLD_W - 1
            ty = random.randint(0, WORLD_H - 1)

        # Find nearest walkable tile
        if not _is_walkable_tile(sim, tx, ty):
            found = _find_nearby_walkable(sim, tx, ty, radius=10)
            if found is None:
                continue
            tx, ty = found

        wx = tx * TILE_SIZE + TILE_SIZE * 0.5
        wy = ty * TILE_SIZE + TILE_SIZE * 0.5
        e = Enemy(wx, wy, raid_number)
        enemies.append(e)
        sim.entities.add(e)

    if enemies:
        sim.event_log.add(
            f"Raid #{raid_number}! {len(enemies)} goblin(s) approaching!",
            (255, 80, 80),
        )
        sim.stats["raids_survived"] = sim.stats.get("raids_survived", 0)

    return enemies


def _is_walkable_tile(sim: "SimulationManager", tx: int, ty: int) -> bool:
    from config import WALKABLE_TILES
    if tx < 0 or tx >= WORLD_W or ty < 0 or ty >= WORLD_H:
        return False
    tile = sim.world.get(tx, ty)
    if tile not in WALKABLE_TILES:
        return False
    # Check walls
    for b in sim.entities.buildings():
        if not b.alive:
            continue
        if b.defn.get("blocks_movement", False):
            tx0, ty0, tx1, ty1 = b.tile_rect
            if tx0 <= tx < tx1 and ty0 <= ty < ty1:
                return False
    return True


def _find_nearby_walkable(sim: "SimulationManager", tx: int, ty: int,
                          radius: int = 10) -> Optional[Tuple[int, int]]:
    for r in range(1, radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                nx, ny = tx + dx, ty + dy
                if _is_walkable_tile(sim, nx, ny):
                    return (nx, ny)
    return None