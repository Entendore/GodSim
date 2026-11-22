"""
achievements.py — Achievement/milestone system and game-over (defeat) detection.

Tracks population milestones, combat victories, economic goals, and
technological progress.  Triggers celebratory event-log messages and
optional on-screen pop-ups.

Also monitors defeat conditions (town hall destroyed with no villagers
left, or all villagers dead).
"""

from __future__ import annotations

from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from simulation import SimulationManager


# ════════════════════════════════════════════════
#  Achievement definitions
# ════════════════════════════════════════════════
class AchievementId:
    """String constants for every achievement."""
    POP_5 = "pop_5"
    POP_10 = "pop_10"
    POP_20 = "pop_20"
    POP_50 = "pop_50"
    FIRST_BUILD = "first_build"
    BUILDER_10 = "builder_10"
    FIRST_KILL = "first_kill"
    KILLER_20 = "killer_20"
    RAID_SURVIVOR_5 = "raid_5"
    RAID_SURVIVOR_10 = "raid_10"
    FIRST_TECH = "first_tech"
    ALL_TECH = "all_tech"
    FOOD_500 = "food_500"
    STONE_200 = "stone_200"
    DAY_10 = "day_10"
    DAY_30 = "day_30"
    DAY_100 = "day_100"
    IRON_MASTER = "iron_50"
    FIRST_ALLY = "first_ally"
    DIPLOMAT = "diplomat"
    WARLORD = "warlord"
    PEACEKEEPER = "peacekeeper"


ACHIEVEMENT_DEFS: Dict[str, dict] = {
    AchievementId.POP_5: {
        "name": "Settling In",
        "desc": "Reach 5 population",
        "color": (150, 220, 150),
    },
    AchievementId.POP_10: {
        "name": "Growing Village",
        "desc": "Reach 10 population",
        "color": (100, 255, 100),
    },
    AchievementId.POP_20: {
        "name": "Thriving Town",
        "desc": "Reach 20 population",
        "color": (50, 255, 50),
    },
    AchievementId.POP_50: {
        "name": "Metropolis",
        "desc": "Reach 50 population",
        "color": (255, 215, 0),
    },
    AchievementId.FIRST_BUILD: {
        "name": "First Construction",
        "desc": "Complete your first building",
        "color": (200, 180, 100),
    },
    AchievementId.BUILDER_10: {
        "name": "Master Builder",
        "desc": "Complete 10 buildings",
        "color": (220, 200, 80),
    },
    AchievementId.FIRST_KILL: {
        "name": "First Blood",
        "desc": "Kill your first enemy",
        "color": (255, 100, 100),
    },
    AchievementId.KILLER_20: {
        "name": "Veteran Commander",
        "desc": "Kill 20 enemies total",
        "color": (255, 50, 50),
    },
    AchievementId.RAID_SURVIVOR_5: {
        "name": "Battle-Hardened",
        "desc": "Survive 5 raids",
        "color": (200, 150, 255),
    },
    AchievementId.RAID_SURVIVOR_10: {
        "name": "Unbreakable",
        "desc": "Survive 10 raids",
        "color": (180, 100, 255),
    },
    AchievementId.FIRST_TECH: {
        "name": "Age of Science",
        "desc": "Research your first technology",
        "color": (100, 200, 255),
    },
    AchievementId.ALL_TECH: {
        "name": "Enlightenment",
        "desc": "Research all 8 technologies",
        "color": (255, 255, 100),
    },
    AchievementId.FOOD_500: {
        "name": "Breadbasket",
        "desc": "Accumulate 500 food",
        "color": (200, 255, 150),
    },
    AchievementId.STONE_200: {
        "name": "Quarry Baron",
        "desc": "Accumulate 200 stone",
        "color": (180, 170, 140),
    },
    AchievementId.DAY_10: {
        "name": "A Decade",
        "desc": "Survive 10 in-game days",
        "color": (220, 200, 180),
    },
    AchievementId.DAY_30: {
        "name": "A Month Passed",
        "desc": "Survive 30 in-game days",
        "color": (200, 180, 220),
    },
    AchievementId.DAY_100: {
        "name": "Centenarian",
        "desc": "Survive 100 in-game days",
        "color": (255, 220, 180),
    },
    AchievementId.IRON_MASTER: {
        "name": "Iron Master",
        "desc": "Mine 50 iron",
        "color": (200, 200, 220),
    },
    AchievementId.FIRST_ALLY: {
        "name": "First Alliance",
        "desc": "Form your first alliance",
        "color": (80, 200, 255),
    },
    AchievementId.DIPLOMAT: {
        "name": "Master Diplomat",
        "desc": "Have 3 simultaneous trade pacts",
        "color": (100, 255, 200),
    },
    AchievementId.WARLORD: {
        "name": "Warlord",
        "desc": "Win 3 wars (enemy peace offer)",
        "color": (255, 100, 50),
    },
    AchievementId.PEACEKEEPER: {
        "name": "Peacekeeper",
        "desc": "Have allies with all discovered villages",
        "color": (200, 255, 200),
    },
}

# Ordered list for display
ACHIEVEMENT_ORDER: List[str] = [
    AchievementId.POP_5, AchievementId.POP_10,
    AchievementId.POP_20, AchievementId.POP_50,
    AchievementId.FIRST_BUILD, AchievementId.BUILDER_10,
    AchievementId.FIRST_KILL, AchievementId.KILLER_20,
    AchievementId.RAID_SURVIVOR_5, AchievementId.RAID_SURVIVOR_10,
    AchievementId.FIRST_TECH, AchievementId.ALL_TECH,
    AchievementId.FOOD_500, AchievementId.STONE_200,
    AchievementId.DAY_10, AchievementId.DAY_30,
    AchievementId.DAY_100, AchievementId.IRON_MASTER,
    AchievementId.FIRST_ALLY, AchievementId.DIPLOMAT,
    AchievementId.WARLORD, AchievementId.PEACEKEEPER,
]


# ════════════════════════════════════════════════
#  AchievementManager
# ════════════════════════════════════════════════
class AchievementManager:
    """Tracks and checks achievements each simulation tick."""

    def __init__(self) -> None:
        self.unlocked: set = set()
        # Pop-up display: (achievement_id, timer_ticks_remaining)
        self._popup: Tuple[str, int] = ("", 0)
        self.popup_timer: int = 0  # frames for animation

    def unlock(self, aid: str, sim: "SimulationManager") -> None:
        if aid in self.unlocked:
            return
        defn = ACHIEVEMENT_DEFS.get(aid)
        if not defn:
            return
        self.unlocked.add(aid)
        sim.event_log.add(
            f"ACHIEVEMENT: {defn['name']} — {defn['desc']}",
            defn["color"],
        )
        sim.stats["achievements"] = sim.stats.get("achievements", 0) + 1
        # Trigger popup
        self._popup = (aid, 180)  # ~3 seconds at 60fps
        self.popup_timer = 180

    @property
    def popup_achievement(self) -> str:
        return self._popup[0] if self._popup[1] > 0 else ""

    @property
    def popup_alpha(self) -> int:
        """Fade out in the last 40 frames."""
        t = self._popup[1]
        if t <= 0:
            return 0
        if t < 40:
            return int(255 * (t / 40))
        return 255

    def tick_frame(self) -> None:
        """Call once per render frame (60fps) to advance popup timer."""
        if self._popup[1] > 0:
            self._popup = (self._popup[0], self._popup[1] - 1)

    def check(self, sim: "SimulationManager") -> None:
        """Check all achievement conditions. Called once per sim tick."""
        pop = sim.population
        stats = sim.stats
        res = sim.global_resources

        # Population
        if pop >= 5:  self.unlock(AchievementId.POP_5, sim)
        if pop >= 10: self.unlock(AchievementId.POP_10, sim)
        if pop >= 20: self.unlock(AchievementId.POP_20, sim)
        if pop >= 50: self.unlock(AchievementId.POP_50, sim)

        # Buildings
        b_completed = stats.get("buildings_completed", 0)
        if b_completed >= 1:  self.unlock(AchievementId.FIRST_BUILD, sim)
        if b_completed >= 10: self.unlock(AchievementId.BUILDER_10, sim)

        # Combat
        kills = stats.get("enemies_killed", 0)
        if kills >= 1:  self.unlock(AchievementId.FIRST_KILL, sim)
        if kills >= 20: self.unlock(AchievementId.KILLER_20, sim)

        # Raids
        raids = stats.get("raids_survived", 0)
        if raids >= 5:  self.unlock(AchievementId.RAID_SURVIVOR_5, sim)
        if raids >= 10: self.unlock(AchievementId.RAID_SURVIVOR_10, sim)

        # Tech
        techs = stats.get("techs_researched", 0)
        if techs >= 1:  self.unlock(AchievementId.FIRST_TECH, sim)
        if len(sim.research.researched) >= 8:
            self.unlock(AchievementId.ALL_TECH, sim)

        # Resources
        if res.get("food", 0) >= 500: self.unlock(AchievementId.FOOD_500, sim)
        if res.get("stone", 0) >= 200: self.unlock(AchievementId.STONE_200, sim)

        # Days survived
        day = sim.day_number
        if day >= 10:  self.unlock(AchievementId.DAY_10, sim)
        if day >= 30:  self.unlock(AchievementId.DAY_30, sim)
        if day >= 100: self.unlock(AchievementId.DAY_100, sim)

        # Iron
        iron_mined = stats.get("iron_mined", 0)
        if iron_mined >= 50: self.unlock(AchievementId.IRON_MASTER, sim)

        # Diplomacy (Phase 7)
        if sim.diplomacy.total_alliances >= 1:
            self.unlock(AchievementId.FIRST_ALLY, sim)
        if sim.diplomacy.pact_count >= 3:
            self.unlock(AchievementId.DIPLOMAT, sim)
        peace_made = stats.get("peace_made", 0)
        if peace_made >= 3:
            self.unlock(AchievementId.WARLORD, sim)
        if (sim.diplomacy._discovered
                and len(sim.diplomacy.villages) > 0
                and all(v.is_allied for v in sim.diplomacy.villages)):
            self.unlock(AchievementId.PEACEKEEPER, sim)

    def check_defeat(self, sim: "SimulationManager") -> bool:
        """Return True if the game is in a defeat state."""
        # Defeat: all villagers dead
        if sim.population <= 0 and sim.total_ticks > 10:
            return True
        # Defeat: town hall destroyed and < 2 villagers
        th = sim.entities.town_hall()
        if th is None or not th.alive:
            if sim.population < 2 and sim.total_ticks > 50:
                return True
        return False

    def check_victory(self, sim: "SimulationManager") -> bool:
        """Return True if a victory condition is met."""
        # Victory: all techs + 30 pop + 10 raids + at least 1 ally
        if (len(sim.research.researched) >= 8 and sim.population >= 30
                and sim.diplomacy.ally_count >= 1):
            raids = sim.stats.get("raids_survived", 0)
            if raids >= 10:
                return True
        # Diplomatic victory: ally with all villages + 20 pop
        if (sim.diplomacy._discovered
                and len(sim.diplomacy.villages) > 0
                and all(v.is_allied for v in sim.diplomacy.villages)
                and sim.population >= 20):
            return True
        return False