"""
pathfinding.py — A* pathfinding with octile heuristic, 8-directional
movement, and diagonal corner-cut prevention.

Replaces the greedy best-first from Phase 2.
"""

from __future__ import annotations

import heapq
import math
from typing import List, Tuple, TYPE_CHECKING

from config import WORLD_W, WORLD_H

if TYPE_CHECKING:
    pass  # world is any object with .get()


def is_walkable(world, tx: int, ty: int, entities=None) -> bool:
    from config import WALKABLE_TILES
    if tx < 0 or tx >= WORLD_W or ty < 0 or ty >= WORLD_H:
        return False
    if world.get(tx, ty) not in WALKABLE_TILES:
        return False
    # Check wall buildings that block movement
    if entities is not None:
        from entities import Building
        for b in entities.buildings():
            if not b.alive:
                continue
            if b.defn.get("blocks_movement", False):
                tx0, ty0, tx1, ty1 = b.tile_rect
                if tx0 <= tx < tx1 and ty0 <= ty < ty1:
                    return False
    return True


# 8-directional offsets (cardinals first for tie-breaking)
_DIRS_8 = [
    (0, -1), (0, 1), (-1, 0), (1, 0),
    (-1, -1), (1, -1), (-1, 1), (1, 1),
]


def _octile(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    """Octile distance — admissible heuristic for 8-dir grids."""
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)


def find_path(
    start: Tuple[int, int],
    goal: Tuple[int, int],
    world,
    max_nodes: int = 600,
    entities=None,
) -> List[Tuple[int, int]]:
    """A* search.  Returns tile list [start, ..., goal] (may be partial).

    *max_nodes* limits exploration to prevent long stalls on
    unreachable goals.  Falls back to greedy if the open set is
    exhausted.
    """
    if start == goal:
        return [start]
    if not is_walkable(world, *goal, entities):
        return [start]

    open_heap: List[Tuple[float, int, Tuple[int, int]]] = []
    # (f_score, tie_breaker, node)
    _counter = 0
    heapq.heappush(open_heap, (_octile(start, goal), _counter, start))
    _counter += 1

    came_from: dict[Tuple[int, int], Tuple[int, int]] = {}
    g_score: dict[Tuple[int, int], float] = {start: 0.0}
    closed: set[Tuple[int, int]] = set()

    while open_heap:
        _f, _c, current = heapq.heappop(open_heap)

        if current == goal:
            # Reconstruct
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        if current in closed:
            continue
        closed.add(current)

        cx, cy = current
        for dx, dy in _DIRS_8:
            nx, ny = cx + dx, cy + dy
            neighbor = (nx, ny)

            if neighbor in closed:
                continue
            if not is_walkable(world, nx, ny, entities):
                continue
            # Diagonal corner-cut prevention
            if dx != 0 and dy != 0:
                if (not is_walkable(world, cx + dx, cy, entities)
                        or not is_walkable(world, cx, cy + dy, entities)):
                    continue

            move_cost = math.sqrt(2) if (dx != 0 and dy != 0) else 1.0
            tentative_g = g_score[current] + move_cost

            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + _octile(neighbor, goal)
                heapq.heappush(open_heap, (f, _counter, neighbor))
                _counter += 1

        if len(closed) >= max_nodes:
            break

    # Partial path: return best node we reached
    if closed:
        best = min(closed, key=lambda n: _octile(n, goal))
        if best != start:
            path = [best]
            while best in came_from:
                best = came_from[best]
                path.append(best)
            path.reverse()
            return path

    return [start]