"""Deux mobilités, deux philosophies.

- TraceMobility  : mobilité SUBIE. Les véhicules suivent une trace
  (CSV t,id,x,y). Le système ne décide rien : il observe et s'adapte.
- UAVKinematics  : mobilité PILOTÉE. Une politique choisit un point de
  passage (x, y, h) ; on s'y rend à vitesse bornée.
"""
from __future__ import annotations

import bisect
import csv
import math
from collections import defaultdict

from .config import resolve


class TraceMobility:
    def __init__(self, path: str):
        data: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
        with open(resolve(path), newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                data[row["id"]].append((float(row["t"]), float(row["x"]), float(row["y"])))
        self.ids = sorted(data)
        self._t = {}
        self._xy = {}
        for vid, rows in data.items():
            rows.sort()
            self._t[vid] = [r[0] for r in rows]
            self._xy[vid] = [(r[1], r[2]) for r in rows]

    def position(self, vid: str, t: float) -> tuple[float, float]:
        ts = self._t[vid]
        xy = self._xy[vid]
        if t <= ts[0]:
            return xy[0]
        if t >= ts[-1]:
            return xy[-1]
        i = bisect.bisect_right(ts, t)
        t0, t1 = ts[i - 1], ts[i]
        a = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        (x0, y0), (x1, y1) = xy[i - 1], xy[i]
        return (x0 + a * (x1 - x0), y0 + a * (y1 - y0))

    def velocity(self, vid: str, t: float, dt: float = 0.1) -> tuple[float, float]:
        x0, y0 = self.position(vid, t - dt)
        x1, y1 = self.position(vid, t + dt)
        return ((x1 - x0) / (2 * dt), (y1 - y0) / (2 * dt))


class UAVKinematics:
    """Déplacement borné vers un point de passage."""

    def __init__(self, pos, speed_mps: float, climb_mps: float):
        self.pos = [float(pos[0]), float(pos[1]), float(pos[2])]
        self.speed = speed_mps
        self.climb = climb_mps
        self.v_h = 0.0
        self.v_z = 0.0

    def step(self, target, dt: float) -> None:
        tx, ty, tz = (float(target[0]), float(target[1]), float(target[2]))
        dx, dy = tx - self.pos[0], ty - self.pos[1]
        d = math.hypot(dx, dy)
        move = min(d, self.speed * dt)
        if d > 1e-9:
            self.pos[0] += dx / d * move
            self.pos[1] += dy / d * move
        self.v_h = move / dt if dt > 0 else 0.0
        dz = tz - self.pos[2]
        mz = max(-self.climb * dt, min(self.climb * dt, dz))
        self.pos[2] += mz
        self.v_z = mz / dt if dt > 0 else 0.0
