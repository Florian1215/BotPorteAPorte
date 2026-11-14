"""Open-path travelling salesman heuristic: nearest neighbour + 2-opt (ported and sped up from the bot)."""
import time


def solve_open_path(dist: list[list[float]], fixed_end: bool = False, max_seconds: float = 3.0) -> list[int]:
    """Return a visiting order of all nodes, starting at node 0.

    If `fixed_end` is True, the last node (index n-1) is forced to be the last of the path
    (free tours: from the start point to the chosen arrival point).
    """
    n = len(dist)
    if n <= 2:
        return list(range(n))

    last = n - 1
    unvisited = set(range(1, last if fixed_end else n))
    tour = [0]
    while unvisited:
        current = tour[-1]
        nxt = min(unvisited, key=lambda k: dist[current][k])
        tour.append(nxt)
        unvisited.remove(nxt)
    if fixed_end:
        tour.append(last)

    # 2-opt on the open path: reverse tour[i..j]. Node 0 never moves; nor does the end if fixed.
    deadline = time.monotonic() + max_seconds
    max_j = n - 2 if fixed_end else n - 1
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        for i in range(1, max_j):
            a, b = tour[i - 1], tour[i]
            for j in range(i + 1, max_j + 1):
                c = tour[j]
                e = tour[j + 1] if j + 1 < n else None
                before = dist[a][b] + (dist[c][e] if e is not None else 0.0)
                after = dist[a][c] + (dist[b][e] if e is not None else 0.0)
                if after < before - 1e-9:
                    tour[i : j + 1] = reversed(tour[i : j + 1])
                    b = tour[i]
                    improved = True
            if time.monotonic() >= deadline:
                break
    return tour
