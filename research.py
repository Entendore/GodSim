"""
research.py — Technology tree manager with prerequisite checking,
research progress tracking, and effect application.

Requires a completed Library building to conduct research.
Scholars speed up research by 2x.
"""

from __future__ import annotations

import random
from typing import Optional, Set, Dict, List, TYPE_CHECKING

from config import (
    Tech, TECH_DEFS, BuildingType,
)

if TYPE_CHECKING:
    from simulation import SimulationManager


# ════════════════════════════════════════════════
#  ResearchManager
# ════════════════════════════════════════════════
class ResearchManager:
    """Tracks researched techs, in-progress research, and applies effects."""

    def __init__(self) -> None:
        self.researched: Set[Tech] = set()
        self.current_research: Optional[Tech] = None
        self.progress: int = 0  # ticks accumulated toward current research
        self.total_needed: int = 0

    # ── queries ──────────────────────────────────
    def is_researched(self, tech: Tech) -> bool:
        return tech in self.researched

    def can_research(self, tech: Tech) -> bool:
        if tech in self.researched:
            return False
        if self.current_research is not None:
            return False
        defn = TECH_DEFS[tech]
        for req in defn["requires"]:
            if req not in self.researched:
                return False
        return True

    def has_library(self, sim: "SimulationManager") -> bool:
        return any(
            b.btype == BuildingType.LIBRARY and b.built and b.alive
            for b in sim.entities.buildings()
        )

    def scholar_count(self, sim: "SimulationManager") -> int:
        from villager import Villager
        from config import Role
        return sum(
            1 for e in sim.entities.all()
            if isinstance(e, Villager) and e.alive and e.role == Role.SCHOLAR
        )

    def available_techs(self) -> List[Tech]:
        return [t for t in Tech if self.can_research(t)]

    # ── actions ──────────────────────────────────
    def start_research(self, tech: Tech, sim: "SimulationManager") -> Optional[str]:
        if not self.can_research(tech):
            return None
        if not self.has_library(sim):
            return "No Library built!"
        defn = TECH_DEFS[tech]
        # Check cost
        for res, amt in defn["cost"].items():
            if sim.global_resources.get(res, 0) < amt:
                return f"Not enough {res}!"
        # Deduct cost
        for res, amt in defn["cost"].items():
            sim.global_resources[res] = sim.global_resources.get(res, 0) - amt
        self.current_research = tech
        self.progress = 0
        self.total_needed = defn["research_ticks"]
        return f"Researching: {defn['name']}"

    def cancel_research(self, sim: "SimulationManager") -> bool:
        if self.current_research is None:
            return False
        # Refund 50% of cost
        defn = TECH_DEFS[self.current_research]
        for res, amt in defn["cost"].items():
            refund = amt // 2
            sim.global_resources[res] = sim.global_resources.get(res, 0) + refund
        sim.event_log.add(
            f"Research cancelled: {defn['name']} (50% refunded)",
            (200, 200, 100),
        )
        self.current_research = None
        self.progress = 0
        return True

    # ── tick ─────────────────────────────────────
    def tick(self, sim: "SimulationManager") -> None:
        if self.current_research is None:
            return
        if not self.has_library(sim):
            return

        # Scholar speed bonus
        scholars = self.scholar_count(sim)
        speed_mult = 1.0 + (scholars * 1.0)

        self.progress += speed_mult

        if self.progress >= self.total_needed:
            self._complete(sim)

    def _complete(self, sim: "SimulationManager") -> None:
        tech = self.current_research
        if tech is None:
            return
        defn = TECH_DEFS[tech]
        self.researched.add(tech)
        self.current_research = None
        self.progress = 0

        self._apply_effect(tech, sim)

        sim.event_log.add(
            f"Research complete: {defn['name']}!",
            (100, 255, 200),
        )
        sim.stats["techs_researched"] = sim.stats.get("techs_researched", 0) + 1
        sim.sounds.play("research")

    def _apply_effect(self, tech: Tech, sim: "SimulationManager") -> None:
        from villager import Villager
        effect = TECH_DEFS[tech]["effect"]

        if effect == "fortify_bonus":
            for b in sim.entities.buildings():
                if b.built and b.alive:
                    old = sim.building_hp.get(b.id, b.defn.get("hp", 100))
                    sim.building_hp[b.id] = int(old * 1.5)

        elif effect == "medicine_bonus":
            for e in sim.entities.all():
                if isinstance(e, Villager) and e.alive:
                    e.max_hp += 20
                    e.hp = min(e.hp + 20, e.max_hp)

        elif effect == "metallurgy_bonus":
            for e in sim.entities.all():
                if isinstance(e, Villager) and e.alive:
                    e.damage = int(e.damage * 1.5)

        elif effect == "carry_bonus":
            for e in sim.entities.all():
                if isinstance(e, Villager) and e.alive:
                    e.max_carry = int(e.max_carry * 1.5)

    # ── convenience checkers ─────────────────────
    def has_gather_bonus(self) -> bool:
        return Tech.BETTER_TOOLS in self.researched

    def has_farm_bonus(self) -> bool:
        return Tech.AGRICULTURE in self.researched

    def has_fortify_bonus(self) -> bool:
        return Tech.FORTIFICATIONS in self.researched

    def has_medicine_bonus(self) -> bool:
        return Tech.MEDICINE in self.researched

    def has_metallurgy(self) -> bool:
        return Tech.METALLURGY in self.researched

    def has_range_bonus(self) -> bool:
        return Tech.ARCHERY in self.researched

    def has_carry_bonus(self) -> bool:
        return Tech.STORAGE_MASTER in self.researched

    def has_trade_bonus(self) -> bool:
        return Tech.TRADE_ROUTES in self.researched

    @property
    def progress_fraction(self) -> float:
        if self.total_needed <= 0:
            return 0.0
        return min(1.0, self.progress / self.total_needed)