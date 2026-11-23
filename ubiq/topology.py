"""Graphe filaire entre « sites » (points de présence : Edge, Cloud...).

Les AP (y compris l'UAV, via sa station sol) sont rattachés à un site.
Le délai one-way entre deux sites est le plus court chemin sur les
liens actifs. Ce graphe est commun aux deux backends (sim et Mininet).
"""
from __future__ import annotations

import heapq


class SiteGraph:
    def __init__(self, sites: dict, links: list[dict]):
        self.sites = list(sites)
        self.links = {}
        for ln in links:
            key = frozenset((ln["a"], ln["b"]))
            self.links[key] = {"a": ln["a"], "b": ln["b"], "delay_ms": float(ln["delay_ms"]),
                               "bw_mbps": float(ln.get("bw_mbps", 100)), "up": True}

    def set_up(self, a: str, b: str, up: bool) -> None:
        self.links[frozenset((a, b))]["up"] = up

    def neighbors(self, s: str):
        for ln in self.links.values():
            if not ln["up"]:
                continue
            if ln["a"] == s:
                yield ln["b"], ln["delay_ms"]
            elif ln["b"] == s:
                yield ln["a"], ln["delay_ms"]

    def path_delay_ms(self, src: str, dst: str) -> float | None:
        """Délai one-way ; None si injoignable."""
        if src == dst:
            return 0.0
        dist = {src: 0.0}
        pq = [(0.0, src)]
        while pq:
            d, s = heapq.heappop(pq)
            if s == dst:
                return d
            if d > dist.get(s, float("inf")):
                continue
            for n, w in self.neighbors(s):
                nd = d + w
                if nd < dist.get(n, float("inf")):
                    dist[n] = nd
                    heapq.heappush(pq, (nd, n))
        return None

    def tree_edges(self) -> list[dict]:
        return list(self.links.values())
