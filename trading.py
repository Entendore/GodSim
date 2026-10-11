"""
trading.py — Merchant caravan system and trade execution.

A Trading Post building enables periodic merchant visits.
Merchants offer resource exchanges that the player can accept.
Trade Routes tech improves the exchange rates.
"""

from __future__ import annotations

import random
from typing import Optional, Dict, List, TYPE_CHECKING

from config import (
    TRADE_MIN_TICKS, TRADE_MAX_TICKS, MERCHANT_STAY_TICKS,
    TRADE_OFFERS, BuildingType, Tech,
)

if TYPE_CHECKING:
    from simulation import SimulationManager


# ════════════════════════════════════════════════
#  TradeOffer (instantiated from TRADE_OFFERS)
# ════════════════════════════════════════════════
class TradeOffer:
    __slots__ = ("give_res", "give_amt", "recv_res", "recv_amt")

    def __init__(self, give_res: str, give_amt: int, recv_res: str, recv_amt: int) -> None:
        self.give_res = give_res
        self.give_amt = give_amt
        self.recv_res = recv_res
        self.recv_amt = recv_amt

    def __repr__(self) -> str:
        return f"{self.give_amt}{self.give_res[0]} -> {self.recv_amt}{self.recv_res[0]}"


# ════════════════════════════════════════════════
#  TradingManager
# ════════════════════════════════════════════════
class TradingManager:
    """Manages merchant caravans and trade offers."""

    def __init__(self) -> None:
        self._cooldown: int = random.randint(TRADE_MIN_TICKS, TRADE_MAX_TICKS)
        self.merchant_present: bool = False
        self._merchant_timer: int = 0
        self.offers: List[TradeOffer] = []
        self.total_trades: int = 0

    def has_trading_post(self, sim: "SimulationManager") -> bool:
        return any(
            b.btype == BuildingType.TRADING_POST and b.built and b.alive
            for b in sim.entities.buildings()
        )

    def tick(self, sim: "SimulationManager") -> None:
        if self.merchant_present:
            self._merchant_timer -= 1
            if self._merchant_timer <= 0:
                self.merchant_present = False
                self.offers.clear()
                sim.event_log.add("Merchant has departed.", (180, 160, 100))
                self._cooldown = random.randint(TRADE_MIN_TICKS, TRADE_MAX_TICKS)
        else:
            self._cooldown -= 1
            if self._cooldown <= 0:
                if self.has_trading_post(sim):
                    self._spawn_merchant(sim)
                else:
                    self._cooldown = random.randint(TRADE_MIN_TICKS, TRADE_MAX_TICKS)

    def _spawn_merchant(self, sim: "SimulationManager") -> None:
        self.merchant_present = True
        self._merchant_timer = MERCHANT_STAY_TICKS

        # Generate 2-3 offers
        self.offers.clear()
        pool = list(TRADE_OFFERS)
        random.shuffle(pool)
        count = min(random.randint(2, 3), len(pool))

        trade_bonus = sim.research.has_trade_bonus() if hasattr(sim, "research") else False

        for i in range(count):
            raw = pool[i]
            recv_amt = raw["receive"][1]
            # Trade Routes tech improves received amount by 40%
            if trade_bonus:
                recv_amt = int(recv_amt * 1.4)
            self.offers.append(TradeOffer(
                give_res=raw["give"][0],
                give_amt=raw["give"][1],
                recv_res=raw["receive"][0],
                recv_amt=recv_amt,
            ))

        sim.event_log.add(
            f"A merchant arrives with {len(self.offers)} trade(s)!",
            (255, 220, 120),
        )

    def execute_trade(self, offer_index: int, sim: "SimulationManager") -> Optional[str]:
        if not self.merchant_present:
            return "No merchant present."
        if offer_index < 0 or offer_index >= len(self.offers):
            return "Invalid trade."
        offer = self.offers[offer_index]

        # Check player has enough
        if sim.global_resources.get(offer.give_res, 0) < offer.give_amt:
            return f"Not enough {offer.give_res}!"

        # Execute
        sim.global_resources[offer.give_res] -= offer.give_amt
        sim.global_resources[offer.recv_res] = sim.global_resources.get(offer.recv_res, 0) + offer.recv_amt

        self.total_trades += 1
        sim.stats["trades_completed"] = sim.stats.get("trades_completed", 0) + 1

        # Remove the used offer
        self.offers.pop(offer_index)

        sim.event_log.add(
            f"Traded {offer.give_amt} {offer.give_res} for {offer.recv_amt} {offer.recv_res}.",
            (200, 220, 150),
        )
        sim.sounds.play("trade")
        return None  # success