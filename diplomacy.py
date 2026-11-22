"""
diplomacy.py — AI village diplomacy system with relationships, alliances,
trade pacts, gifts, tributes, and war mechanics.

Requires an Embassy building to conduct diplomacy.
AI villages have personalities that influence their behavior.
"""

from __future__ import annotations

import random
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

from config import (
    DIPLO_EVENT_MIN_TICKS, DIPLO_EVENT_MAX_TICKS,
    DIPLO_MAX_VILLAGES, DIPLO_VILLAGE_NAMES, DIPLO_PERSONALITIES,
    RELATION_ALLY, RELATION_FRIENDLY, RELATION_NEUTRAL_LOW, RELATION_HOSTILE,
    GIFT_RELATION_BONUS, TRADE_PACT_BONUS, ALLIANCE_BONUS,
    TRIBUTE_FAIL_PENALTY, WAR_DECLARE_PENALTY, PEACE_PROPOSAL_BONUS,
    BuildingType, WORLD_W, WORLD_H,
)

if TYPE_CHECKING:
    from simulation import SimulationManager


# ════════════════════════════════════════════════
#  Relationship status helper
# ════════════════════════════════════════════════
def relation_status(score: int) -> str:
    if score >= RELATION_ALLY:
        return "Allied"
    elif score >= RELATION_FRIENDLY:
        return "Friendly"
    elif score >= RELATION_NEUTRAL_LOW:
        return "Neutral"
    elif score >= RELATION_HOSTILE:
        return "Unfriendly"
    else:
        return "Hostile"


def relation_color(score: int) -> Tuple[int, int, int]:
    if score >= RELATION_ALLY:
        return (80, 200, 255)
    elif score >= RELATION_FRIENDLY:
        return (100, 255, 100)
    elif score >= RELATION_NEUTRAL_LOW:
        return (200, 200, 150)
    elif score >= RELATION_HOSTILE:
        return (255, 180, 80)
    else:
        return (255, 80, 80)


# ════════════════════════════════════════════════
#  AIVillage
# ════════════════════════════════════════════════
class AIVillage:
    """An AI-controlled village with personality and resources."""

    def __init__(self, name: str, personality: str,
                 map_tx: int, map_ty: int) -> None:
        self.name: str = name
        self.personality: str = personality  # aggressive/peaceful/trading/isolationist
        self.map_tx: int = map_tx  # Position on the world map (for minimap display)
        self.map_ty: int = map_ty

        # Relationship with the player (-100 to 100)
        self.relation: int = random.randint(-10, 15)

        # Diplomatic state
        self.at_war: bool = False
        self.has_trade_pact: bool = False
        self.is_allied: bool = False
        self.war_ticks: int = 0  # How long the war has lasted

        # Abstract strength (affects tribute demands and war difficulty)
        self.military_strength: int = random.randint(3, 12)
        self.wealth: int = random.randint(20, 80)

        # AI event cooldown
        self.event_cooldown: int = random.randint(
            DIPLO_EVENT_MIN_TICKS, DIPLO_EVENT_MAX_TICKS
        )

        # Pending proposal from this village (for player to respond)
        self.pending_proposal: Optional[Dict] = None
        self.proposal_timer: int = 0  # Ticks before proposal expires

    def clamp_relation(self) -> None:
        self.relation = max(-100, min(100, self.relation))

    def change_relation(self, amount: int) -> int:
        """Change relationship and return the new value."""
        self.relation += amount
        self.clamp_relation()
        return self.relation

    def update_state_from_relation(self) -> None:
        """Sync diplomatic state flags with the current relationship score."""
        # War overrides everything
        if self.at_war:
            return
        self.is_allied = self.relation >= RELATION_ALLY
        # Trade pact requires friendly or better
        if self.relation < RELATION_FRIENDLY:
            self.has_trade_pact = False


# ════════════════════════════════════════════════
#  DiplomacyManager
# ════════════════════════════════════════════════
class DiplomacyManager:
    """Manages all AI villages, diplomatic events, and player actions."""

    def __init__(self) -> None:
        self.villages: List[AIVillage] = []
        self._discovered: bool = False  # Whether AI villages have been discovered
        self._initialize_cooldown: int = 200  # Discover after 20s
        self.total_gifts_sent: int = 0
        self.total_alliances: int = 0
        self.total_wars: int = 0

    def has_embassy(self, sim: "SimulationManager") -> bool:
        return any(
            b.btype == BuildingType.EMBASSY and b.built and b.alive
            for b in sim.entities.buildings()
        )

    # ── Initialization ──────────────────────────
    def _discover_villages(self, sim: "SimulationManager") -> None:
        """Create AI villages at random positions around the map."""
        if self._discovered:
            return
        self._initialize_cooldown -= 1
        if self._initialize_cooldown > 0:
            return
        # Need an embassy to discover
        if not self.has_embassy(sim):
            self._initialize_cooldown = 100  # Check again in 10s
            return

        names = list(DIPLO_VILLAGE_NAMES)
        random.shuffle(names)
        count = min(random.randint(3, DIPLO_MAX_VILLAGES), len(names))

        for i in range(count):
            # Place at map edges/mid-distances
            attempts = 0
            while attempts < 50:
                edge = random.randint(0, 3)
                if edge == 0:
                    tx = random.randint(10, WORLD_W - 10)
                    ty = random.randint(5, 20)
                elif edge == 1:
                    tx = random.randint(10, WORLD_W - 10)
                    ty = random.randint(WORLD_H - 20, WORLD_H - 5)
                elif edge == 2:
                    tx = random.randint(5, 20)
                    ty = random.randint(10, WORLD_H - 10)
                else:
                    tx = random.randint(WORLD_W - 20, WORLD_W - 5)
                    ty = random.randint(10, WORLD_H - 10)
                # Check not too close to another village
                too_close = False
                for v in self.villages:
                    if abs(v.map_tx - tx) < 20 and abs(v.map_ty - ty) < 20:
                        too_close = True
                        break
                if not too_close:
                    break
                attempts += 1

            personality = random.choice(DIPLO_PERSONALITIES)
            village = AIVillage(names[i], personality, tx, ty)
            # Personality affects starting relation
            if personality == "peaceful":
                village.relation = random.randint(5, 25)
            elif personality == "aggressive":
                village.relation = random.randint(-15, 5)
            elif personality == "trading":
                village.relation = random.randint(0, 20)
            else:  # isolationist
                village.relation = random.randint(-5, 10)
            village.clamp_relation()
            self.villages.append(village)

        self._discovered = True
        sim.event_log.add(
            f"Diplomacy: Discovered {len(self.villages)} neighboring villages! "
            f"Press D to open diplomacy panel.",
            (100, 180, 255),
        )
        sim.sounds.play("research")

    # ── Player actions ───────────────────────────
    def send_gift(self, village_idx: int, sim: "SimulationManager") -> Optional[str]:
        """Send a gift of food to improve relations."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if v.at_war:
            return f"Cannot send gifts while at war with {v.name}."

        gift_cost = 10 + village_idx * 2
        food = sim.global_resources.get("food", 0)
        if food < gift_cost:
            return f"Not enough food! Need {gift_cost}, have {food}."

        sim.global_resources["food"] = food - gift_cost
        bonus = GIFT_RELATION_BONUS
        # Personality modifier
        if v.personality == "trading":
            bonus = int(bonus * 1.3)
        elif v.personality == "isolationist":
            bonus = int(bonus * 0.7)
        elif v.personality == "aggressive":
            bonus = int(bonus * 0.8)

        v.change_relation(bonus)
        v.wealth += gift_cost
        self.total_gifts_sent += 1
        sim.stats["gifts_sent"] = sim.stats.get("gifts_sent", 0) + 1
        v.update_state_from_relation()

        sim.event_log.add(
            f"Sent {gift_cost} food to {v.name}. "
            f"Relation: {v.relation} ({relation_status(v.relation)})",
            (100, 220, 150),
        )
        sim.sounds.play("trade")
        return None

    def propose_trade_pact(self, village_idx: int, sim: "SimulationManager") -> Optional[str]:
        """Propose a trade pact with a village."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if v.at_war:
            return f"Cannot trade with {v.name} while at war."
        if v.has_trade_pact:
            return f"Already have a trade pact with {v.name}."
        if v.relation < RELATION_FRIENDLY:
            return f"{v.name} refuses — relations too low ({v.relation}). Need {RELATION_FRIENDLY}+."

        # Success chance based on relation and personality
        chance = 0.5 + (v.relation - RELATION_FRIENDLY) / 100.0
        if v.personality == "trading":
            chance += 0.3
        elif v.personality == "isolationist":
            chance -= 0.3
        elif v.personality == "aggressive":
            chance -= 0.1

        if random.random() < chance:
            v.has_trade_pact = True
            v.change_relation(TRADE_PACT_BONUS)
            sim.stats["trade_pacts"] = sim.stats.get("trade_pacts", 0) + 1
            sim.event_log.add(
                f"Trade pact established with {v.name}!",
                (100, 255, 200),
            )
            sim.sounds.play("research")
        else:
            v.change_relation(-3)
            sim.event_log.add(
                f"{v.name} declined the trade pact.",
                (255, 180, 100),
            )
        return None

    def propose_alliance(self, village_idx: int, sim: "SimulationManager") -> Optional[str]:
        """Propose a military alliance with a village."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if v.at_war:
            return f"Cannot ally with {v.name} while at war."
        if v.is_allied:
            return f"Already allied with {v.name}."
        if v.relation < RELATION_ALLY:
            return f"{v.name} refuses — need Allied relations ({RELATION_ALLY}+). Current: {v.relation}."

        # Success chance
        chance = 0.4 + (v.relation - RELATION_ALLY) / 100.0
        if v.personality == "peaceful":
            chance += 0.2
        elif v.personality == "isolationist":
            chance -= 0.4
        elif v.personality == "aggressive":
            chance -= 0.2

        if random.random() < chance:
            v.is_allied = True
            v.change_relation(ALLIANCE_BONUS)
            self.total_alliances += 1
            sim.stats["alliances_formed"] = sim.stats.get("alliances_formed", 0) + 1
            sim.event_log.add(
                f"Military alliance formed with {v.name}!",
                (80, 200, 255),
            )
            sim.sounds.play("achievement")
        else:
            v.change_relation(-5)
            sim.event_log.add(
                f"{v.name} declined the alliance offer.",
                (255, 180, 100),
            )
        return None

    def demand_tribute(self, village_idx: int, sim: "SimulationManager") -> Optional[str]:
        """Demand resources from a weaker village."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if v.at_war:
            return f"{v.name} is already at war with you!"
        if v.is_allied:
            return f"Cannot demand tribute from an ally ({v.name})."

        # Need military advantage
        guard_count = sim.guard_count
        if guard_count < v.military_strength:
            return f"Need more guards ({v.military_strength}) to demand tribute from {v.name}."

        # Success based on strength advantage
        chance = 0.3 + (guard_count - v.military_strength) * 0.1
        if v.personality == "aggressive":
            chance -= 0.2

        if random.random() < chance:
            # They pay
            tribute = random.randint(5, 15)
            res = random.choice(["food", "wood", "stone"])
            sim.global_resources[res] = sim.global_resources.get(res, 0) + tribute
            v.change_relation(-8)
            v.wealth -= tribute
            sim.stats["tribute_received"] = sim.stats.get("tribute_received", 0) + tribute
            sim.event_log.add(
                f"{v.name} pays {tribute} {res} as tribute!",
                (255, 220, 100),
            )
            sim.sounds.play("trade")
        else:
            v.change_relation(TRIBUTE_FAIL_PENALTY)
            # They might declare war
            if v.relation < RELATION_HOSTILE and v.personality == "aggressive":
                v.at_war = True
                v.is_allied = False
                v.has_trade_pact = False
                self.total_wars += 1
                sim.event_log.add(
                    f"{v.name} refuses and DECLARES WAR!",
                    (255, 50, 50),
                )
                sim.sounds.play("raid")
            else:
                sim.event_log.add(
                    f"{v.name} refuses the tribute demand! Relation: {v.relation}",
                    (255, 150, 100),
                )
        return None

    def declare_war(self, village_idx: int, sim: "SimulationManager") -> Optional[str]:
        """Declare war on a village."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if v.at_war:
            return f"Already at war with {v.name}."
        if v.is_allied:
            v.change_relation(-40)
            sim.event_log.add(
                f"You break the alliance with {v.name}! Other villages will remember this.",
                (255, 100, 100),
            )
            # Penalize relations with other peaceful villages
            for other in self.villages:
                if other != v and other.personality == "peaceful":
                    other.change_relation(-10)

        v.at_war = True
        v.war_ticks = 0
        v.is_allied = False
        v.has_trade_pact = False
        v.change_relation(WAR_DECLARE_PENALTY)
        self.total_wars += 1
        sim.stats["wars_declared"] = sim.stats.get("wars_declared", 0) + 1
        sim.event_log.add(
            f"You declare war on {v.name}!",
            (255, 60, 60),
        )
        sim.sounds.play("raid")
        return None

    def propose_peace(self, village_idx: int, sim: "SimulationManager") -> Optional[str]:
        """Offer peace to a village at war."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if not v.at_war:
            return f"Not at war with {v.name}."

        # Cost: some food as a peace offering
        peace_cost = 15
        food = sim.global_resources.get("food", 0)
        if food < peace_cost:
            return f"Not enough food for peace offering! Need {peace_cost}."

        # Chance increases with war duration and decreases for aggressive personalities
        chance = 0.3 + min(v.war_ticks / 500.0, 0.4)
        if v.personality == "peaceful":
            chance += 0.3
        elif v.personality == "aggressive":
            chance -= 0.2
        elif v.personality == "isolationist":
            chance += 0.1

        if random.random() < chance:
            sim.global_resources["food"] = food - peace_cost
            v.at_war = False
            v.war_ticks = 0
            v.change_relation(PEACE_PROPOSAL_BONUS)
            v.update_state_from_relation()
            sim.stats["peace_made"] = sim.stats.get("peace_made", 0) + 1
            sim.event_log.add(
                f"Peace established with {v.name}! Relation: {v.relation}",
                (150, 255, 150),
            )
            sim.sounds.play("research")
        else:
            sim.event_log.add(
                f"{v.name} rejects the peace offer!",
                (255, 150, 100),
            )
        return None

    def respond_to_proposal(self, village_idx: int, accept: bool,
                            sim: "SimulationManager") -> Optional[str]:
        """Respond to a pending proposal from an AI village."""
        if not self._discovered:
            return "No villages discovered yet."
        if village_idx < 0 or village_idx >= len(self.villages):
            return "Invalid village."
        v = self.villages[village_idx]
        if v.pending_proposal is None:
            return f"No pending proposal from {v.name}."

        proposal = v.pending_proposal
        v.pending_proposal = None
        v.proposal_timer = 0

        ptype = proposal.get("type", "")

        if accept:
            if ptype == "gift":
                res = proposal["resource"]
                amt = proposal["amount"]
                sim.global_resources[res] = sim.global_resources.get(res, 0) + amt
                v.change_relation(GIFT_RELATION_BONUS // 2)
                sim.event_log.add(
                    f"Accepted gift from {v.name}: +{amt} {res}",
                    (100, 255, 200),
                )
            elif ptype == "trade":
                # Auto-execute the trade
                give_res, give_amt = proposal["give"]
                recv_res, recv_amt = proposal["receive"]
                if sim.global_resources.get(give_res, 0) >= give_amt:
                    sim.global_resources[give_res] -= give_amt
                    sim.global_resources[recv_res] = sim.global_resources.get(recv_res, 0) + recv_amt
                    v.change_relation(TRADE_PACT_BONUS // 2)
                    sim.stats["diplo_trades"] = sim.stats.get("diplo_trades", 0) + 1
                    sim.event_log.add(
                        f"Trade with {v.name}: {give_amt}{give_res[0]} -> {recv_amt}{recv_res[0]}",
                        (200, 220, 150),
                    )
                    sim.sounds.play("trade")
                else:
                    v.change_relation(-5)
                    sim.event_log.add(
                        f"Not enough {give_res} for the trade with {v.name}!",
                        (255, 100, 100),
                    )
            elif ptype == "peace":
                if v.at_war:
                    v.at_war = False
                    v.war_ticks = 0
                    v.change_relation(PEACE_PROPOSAL_BONUS)
                    v.update_state_from_relation()
                    sim.stats["peace_made"] = sim.stats.get("peace_made", 0) + 1
                    sim.event_log.add(
                        f"Peace agreement with {v.name}!",
                        (150, 255, 150),
                    )
                    sim.sounds.play("research")
            elif ptype == "alliance_request":
                if v.relation >= RELATION_FRIENDLY:
                    v.is_allied = True
                    v.change_relation(ALLIANCE_BONUS)
                    self.total_alliances += 1
                    sim.stats["alliances_formed"] = sim.stats.get("alliances_formed", 0) + 1
                    sim.event_log.add(
                        f"Alliance accepted with {v.name}!",
                        (80, 200, 255),
                    )
                    sim.sounds.play("achievement")
                else:
                    sim.event_log.add("Relations too low for alliance.", (255, 150, 100))
            sim.sounds.play("place")
        else:
            # Reject
            if ptype == "gift":
                v.change_relation(-5)
                sim.event_log.add(f"Rejected {v.name}'s gift.", (200, 180, 150))
            elif ptype == "trade":
                v.change_relation(-3)
                sim.event_log.add(f"Rejected {v.name}'s trade offer.", (200, 180, 150))
            elif ptype == "peace":
                v.change_relation(-8)
                sim.event_log.add(f"Rejected {v.name}'s peace offer.", (255, 150, 100))
            elif ptype == "alliance_request":
                v.change_relation(-5)
                sim.event_log.add(f"Rejected {v.name}'s alliance request.", (200, 180, 150))
            elif ptype == "tribute_demand":
                # Refusing tribute may lead to war
                v.change_relation(-15)
                if v.personality == "aggressive" and random.random() < 0.5:
                    v.at_war = True
                    v.war_ticks = 0
                    v.is_allied = False
                    v.has_trade_pact = False
                    self.total_wars += 1
                    sim.event_log.add(
                        f"{v.name} declares war after tribute refusal!",
                        (255, 50, 50),
                    )
                    sim.sounds.play("raid")
                else:
                    sim.event_log.add(
                        f"Refused {v.name}'s tribute demand. Relation: {v.relation}",
                        (255, 180, 100),
                    )
        return None

    # ── AI event tick ────────────────────────────
    def tick(self, sim: "SimulationManager") -> None:
        """Called every simulation tick."""
        self._discover_villages(sim)

        if not self._discovered:
            return

        # Process trade pact benefits
        self._tick_trade_pacts(sim)

        # Process war effects
        self._tick_wars(sim)

        # AI village events
        for v in self.villages:
            # Proposal timer
            if v.pending_proposal is not None:
                v.proposal_timer -= 1
                if v.proposal_timer <= 0:
                    # Proposal expired — auto-reject
                    ptype = v.pending_proposal.get("type", "")
                    v.change_relation(-3 if ptype != "tribute_demand" else 5)
                    v.pending_proposal = None
                    continue

            v.event_cooldown -= 1
            if v.event_cooldown <= 0:
                self._ai_event(v, sim)
                v.event_cooldown = random.randint(
                    DIPLO_EVENT_MIN_TICKS, DIPLO_EVENT_MAX_TICKS
                )

    def _tick_trade_pacts(self, sim: "SimulationManager") -> None:
        """Every ~30 ticks, trade pacts give small resources."""
        if sim.total_ticks % 30 != 0:
            return
        for v in self.villages:
            if v.has_trade_pact and not v.at_war:
                # Small periodic bonus
                bonus_res = random.choice(["food", "wood", "stone"])
                bonus_amt = random.randint(1, 3)
                sim.global_resources[bonus_res] = sim.global_resources.get(bonus_res, 0) + bonus_amt

    def _tick_wars(self, sim: "SimulationManager") -> None:
        """War effects: periodic raids, relation drift."""
        for v in self.villages:
            if not v.at_war:
                continue
            v.war_ticks += 1
            # War gradually worsens relations
            if sim.total_ticks % 50 == 0:
                v.change_relation(-1)
            # Periodic war raids (spawn extra enemies)
            if v.war_ticks % 300 == 0 and v.war_ticks > 0:
                self._war_raid(v, sim)
            # Allies may offer peace after long wars
            if v.war_ticks > 400 and v.personality == "peaceful" and random.random() < 0.02:
                v.pending_proposal = {"type": "peace"}
                v.proposal_timer = 100
                sim.event_log.add(
                    f"{v.name} requests peace!",
                    (200, 200, 100),
                )

    def _war_raid(self, v: AIVillage, sim: "SimulationManager") -> None:
        """Spawn a small raid from a village at war."""
        from enemy import spawn_raid, Enemy
        # Spawn a mini-raid scaled by village strength
        sim.raid_number += 1
        count = min(1 + v.military_strength // 3, 5)
        from config import TILE_SIZE, WALKABLE_TILES
        tx = max(0, min(v.map_tx, WORLD_W - 1))
        ty = max(0, min(v.map_ty, WORLD_H - 1))
        from config import TileType as TT
        if sim.world.get(tx, ty) not in WALKABLE_TILES:
            return
        from enemy import _find_nearby_walkable
        walkable = _find_nearby_walkable(sim, tx, ty, 5)
        if walkable is None:
            return
        tx, ty = walkable
        for _ in range(count):
            wx = tx * TILE_SIZE + TILE_SIZE * 0.5
            wy = ty * TILE_SIZE + TILE_SIZE * 0.5
            e = Enemy(wx, wy, sim.raid_number)
            sim.entities.add(e)
        sim._raid_active = True
        sim.event_log.add(
            f"War raid from {v.name}! {count} enemies!",
            (255, 60, 60),
        )
        sim.sounds.play("raid")

    def _ai_event(self, v: AIVillage, sim: "SimulationManager") -> None:
        """Generate a random diplomatic event from an AI village."""
        if v.at_war:
            return  # Handled by war ticks

        if v.pending_proposal is not None:
            return  # Don't stack proposals

        r = random.random()

        if v.personality == "aggressive":
            if r < 0.2 and v.relation < 0:
                # Demand tribute
                amt = random.randint(5, 10 + v.military_strength)
                res = random.choice(["food", "wood", "stone"])
                v.pending_proposal = {
                    "type": "tribute_demand",
                    "resource": res,
                    "amount": amt,
                    "demand_text": f"{v.name} demands {amt} {res} as tribute!",
                }
                v.proposal_timer = 80
                sim.event_log.add(v.pending_proposal["demand_text"], (255, 180, 80))
                return
            elif r < 0.35 and v.relation < RELATION_HOSTILE:
                # Declare war
                v.at_war = True
                v.war_ticks = 0
                v.is_allied = False
                v.has_trade_pact = False
                self.total_wars += 1
                sim.event_log.add(
                    f"{v.name} declares war on you!",
                    (255, 50, 50),
                )
                sim.sounds.play("raid")
                return

        if v.personality == "peaceful":
            if r < 0.25:
                # Send a gift
                res = random.choice(["food", "wood"])
                amt = random.randint(3, 8)
                v.pending_proposal = {"type": "gift", "resource": res, "amount": amt}
                v.proposal_timer = 100
                sim.event_log.add(
                    f"{v.name} offers {amt} {res} as a gift!",
                    (150, 220, 255),
                )
                return
            elif r < 0.35 and v.relation >= RELATION_FRIENDLY and not v.is_allied:
                v.pending_proposal = {"type": "alliance_request"}
                v.proposal_timer = 100
                sim.event_log.add(
                    f"{v.name} proposes an alliance!",
                    (100, 200, 255),
                )
                return

        if v.personality == "trading":
            if r < 0.35 and not v.has_trade_pact:
                # Propose a trade
                give_res = random.choice(["food", "wood", "stone"])
                recv_res = random.choice(["food", "wood", "stone"])
                while recv_res == give_res:
                    recv_res = random.choice(["food", "wood", "stone"])
                give_amt = random.randint(5, 12)
                recv_amt = int(give_amt * random.uniform(0.8, 1.3))
                v.pending_proposal = {
                    "type": "trade",
                    "give": (give_res, give_amt),
                    "receive": (recv_res, recv_amt),
                }
                v.proposal_timer = 80
                sim.event_log.add(
                    f"{v.name} offers: {give_amt}{give_res[0]} -> {recv_amt}{recv_res[0]}",
                    (220, 200, 100),
                )
                return

        if v.personality == "isolationist":
            if r < 0.1:
                # Rare gift
                amt = random.randint(2, 5)
                v.pending_proposal = {"type": "gift", "resource": "food", "amount": amt}
                v.proposal_timer = 80
                sim.event_log.add(
                    f"{v.name} sends a small gift of {amt} food.",
                    (180, 180, 180),
                )
                return

        # Default: slight relation drift toward 0
        if v.relation > 0:
            v.change_relation(-1)
        elif v.relation < 0:
            v.change_relation(1)

    # ── Alliance reinforcement ───────────────────
    def get_allied_reinforcements(self, sim: "SimulationManager") -> int:
        """When a raid is active, allied villages may send reinforcement guards."""
        if not sim._raid_active:
            return 0
        total = 0
        for v in self.villages:
            if v.is_allied and not v.at_war:
                if random.random() < 0.3:  # 30% chance per allied village per raid
                    total += random.randint(1, 3)
        return total

    # ── Queries ──────────────────────────────────
    @property
    def ally_count(self) -> int:
        return sum(1 for v in self.villages if v.is_allied)

    @property
    def war_count(self) -> int:
        return sum(1 for v in self.villages if v.at_war)

    @property
    def pact_count(self) -> int:
        return sum(1 for v in self.villages if v.has_trade_pact)


# ════════════════════════════════════════════════
#  Diplomacy Panel Drawing
# ════════════════════════════════════════════════
def draw_diplomacy_panel(screen, sim, font, font_sm, font_ev):
    """Draw the diplomacy overlay panel."""
    dm = sim.diplomacy
    if not dm._discovered:
        # Show hint
        sw, sh = screen.get_size()
        pw, ph = 380, 80
        px = (sw - pw) // 2
        py = (sh - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill((20, 20, 35, 220))
        screen.blit(bg, (px, py))
        pygame.draw.rect(screen, (100, 140, 180), (px, py, pw, ph), 2, border_radius=6)
        t = font.render("DIPLOMACY", True, (100, 180, 255))
        screen.blit(t, (px + pw // 2 - t.get_width() // 2, py + 8))
        has_emb = dm.has_embassy(sim)
        if not has_emb:
            h = font_sm.render("Build an Embassy to discover neighboring villages.", True, (200, 150, 150))
        else:
            h = font_sm.render("Scouting for neighboring villages...", True, (180, 180, 200))
        screen.blit(h, (px + pw // 2 - h.get_width() // 2, py + 35))
        h2 = font_ev.render("Press D to close", True, (140, 140, 160))
        screen.blit(h2, (px + pw // 2 - h2.get_width() // 2, py + ph - 22))
        return

    import pygame

    sw, sh = screen.get_size()
    n_villages = len(dm.villages)
    row_h = 82
    panel_w = 580
    panel_h = 70 + n_villages * row_h + 40
    if panel_h > sh - 40:
        panel_h = sh - 40
    px = (sw - panel_w) // 2
    py = (sh - panel_h) // 2

    bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    bg.fill((20, 20, 35, 225))
    screen.blit(bg, (px, py))
    pygame.draw.rect(screen, (100, 140, 180), (px, py, panel_w, panel_h), 2, border_radius=6)

    # Title
    title = font.render("DIPLOMACY", True, (100, 180, 255))
    screen.blit(title, (px + panel_w // 2 - title.get_width() // 2, py + 8))

    # Summary line
    summary = (f"Allies:{dm.ally_count}  Pacts:{dm.pact_count}  "
               f"Wars:{dm.war_count}  Villages:{n_villages}")
    screen.blit(font_ev.render(summary, True, (160, 160, 180)), (px + 10, py + 32))

    # Embassy status
    has_emb = dm.has_embassy(sim)
    emb_col = (100, 255, 100) if has_emb else (255, 100, 100)
    emb_txt = "Embassy: Active" if has_emb else "Embassy: NEEDED"
    screen.blit(font_ev.render(emb_txt, True, emb_col), (px + panel_w - 150, py + 32))

    # Village rows
    y_start = py + 52
    for idx, v in enumerate(dm.villages):
        if y_start + row_h > py + panel_h - 30:
            break
        ry = y_start + idx * row_h

        # Row background
        row_bg = pygame.Surface((panel_w - 20, row_h - 4), pygame.SRCALPHA)
        if v.at_war:
            row_bg.fill((60, 20, 20, 120))
        elif v.is_allied:
            row_bg.fill((20, 30, 60, 120))
        else:
            row_bg.fill((30, 30, 30, 80))
        screen.blit(row_bg, (px + 10, ry))

        # Village name and personality
        name_color = (255, 80, 80) if v.at_war else ((80, 200, 255) if v.is_allied else (220, 220, 220))
        pers_icons = {"aggressive": "A", "peaceful": "P", "trading": "T", "isolationist": "I"}
        pers_colors = {
            "aggressive": (255, 100, 100),
            "peaceful": (100, 255, 100),
            "trading": (255, 220, 100),
            "isolationist": (160, 160, 160),
        }
        screen.blit(
            font_sm.render(f"[{idx+1}] {v.name}", True, name_color),
            (px + 15, ry + 2),
        )
        screen.blit(
            font_ev.render(f"({pers_icons.get(v.personality, '?')}) {v.personality}",
                           True, pers_colors.get(v.personality, (200, 200, 200))),
            (px + 15, ry + 18),
        )

        # Relationship bar
        bar_x = px + 200
        bar_y = ry + 5
        bar_w = 180
        bar_h = 12
        pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
        # Map relation from [-100, 100] to [0, bar_w]
        fill_w = int((v.relation + 100) / 200.0 * bar_w)
        fill_w = max(0, min(bar_w, fill_w))
        rc = relation_color(v.relation)
        pygame.draw.rect(screen, rc, (bar_x, bar_y, fill_w, bar_h))
        pygame.draw.rect(screen, (80, 80, 100), (bar_x, bar_y, bar_w, bar_h), 1)
        # Relation text
        status = relation_status(v.relation)
        if v.at_war:
            status = "AT WAR"
            rc = (255, 50, 50)
        screen.blit(
            font_ev.render(f"{v.relation:+d} {status}", True, rc),
            (bar_x, bar_y + 14),
        )

        # Diplomatic state tags
        tag_x = px + 400
        tag_y = ry + 4
        if v.at_war:
            screen.blit(font_ev.render("WAR", True, (255, 60, 60)), (tag_x, tag_y))
        if v.is_allied:
            screen.blit(font_ev.render("ALLY", True, (80, 200, 255)), (tag_x, tag_y))
        if v.has_trade_pact:
            screen.blit(font_ev.render("PACT", True, (100, 255, 100)), (tag_x + 40, tag_y))
        # Military strength
        screen.blit(
            font_ev.render(f"Str:{v.military_strength}", True, (180, 160, 140)),
            (tag_x, tag_y + 16),
        )

        # Action keys
        if v.pending_proposal is not None:
            ptype = v.pending_proposal.get("type", "")
            if ptype == "tribute_demand":
                action_text = f"F:Refuse  J:Pay({v.pending_proposal['amount']}{v.pending_proposal['resource'][0]})"
            else:
                action_text = "J:Accept  F:Reject"
            screen.blit(
                font_ev.render(action_text, True, (255, 220, 100)),
                (px + 15, ry + 36),
            )
            # Proposal description
            if ptype == "gift":
                pdesc = f"Offers {v.pending_proposal['amount']} {v.pending_proposal['resource']}"
            elif ptype == "trade":
                g = v.pending_proposal["give"]
                r = v.pending_proposal["receive"]
                pdesc = f"Trade: {g[1]}{g[0][0]} -> {r[1]}{r[0][0]}"
            elif ptype == "peace":
                pdesc = "Requests peace"
            elif ptype == "alliance_request":
                pdesc = "Proposes alliance"
            elif ptype == "tribute_demand":
                pdesc = v.pending_proposal.get("demand_text", "Demands tribute!")
            else:
                pdesc = "?"
            screen.blit(
                font_ev.render(pdesc, True, (220, 200, 150)),
                (px + 15, ry + 52),
            )
        else:
            # Normal action keys
            if v.at_war:
                keys_text = "K:Peace  (at war)"
            else:
                keys_text = "G:Gift  T:Pact  A:Ally  D:Tribute  W:War"
            screen.blit(
                font_ev.render(keys_text, True, (120, 120, 140)),
                (px + 15, ry + 36),
            )

    # Bottom hint
    hint_y = py + panel_h - 20
    hints = "G:Gift  T:TradePact  A:Ally  D:Tribute  W:War  K:Peace  J:Accept  F:Reject  D(close)"
    h = font_ev.render(hints, True, (120, 120, 140))
    screen.blit(h, (px + panel_w // 2 - h.get_width() // 2, hint_y))