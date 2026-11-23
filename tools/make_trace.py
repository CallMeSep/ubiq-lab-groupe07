#!/usr/bin/env python3
"""Génère une trace de mobilité véhiculaire simple (CSV t,id,x,y).

Route rectiligne de L mètres, deux sens (y = 0 et y = 8), demi-tour aux
extrémités, un feu tricolore au milieu (cycle rouge/vert). Déterministe.

  python3 tools/make_trace.py --out scenarios/traces/road_600m.csv
"""
import argparse
import csv
import random


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scenarios/traces/road_600m.csv")
    ap.add_argument("--length", type=float, default=600.0)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--duration", type=float, default=200.0)
    ap.add_argument("--dt", type=float, default=0.1)
    ap.add_argument("--light_x", type=float, default=300.0)
    ap.add_argument("--red_s", type=float, default=15.0)
    ap.add_argument("--green_s", type=float, default=25.0)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    veh = []
    for i in range(a.n):
        direction = 1 if i % 2 == 0 else -1
        veh.append({
            "id": f"V{i + 1}",
            "x": rng.uniform(20, a.length - 20),
            "dir": direction,
            "vmax": rng.uniform(8.0, 15.0),   # 29 à 54 km/h (urbain)
            "v": 0.0,
        })
    cycle = a.red_s + a.green_s
    rows = []
    t = 0.0
    while t <= a.duration + 1e-9:
        red = (t % cycle) < a.red_s
        for v in veh:
            y = 0.0 if v["dir"] > 0 else 8.0
            rows.append({"t": round(t, 2), "id": v["id"], "x": round(v["x"], 2), "y": y})
            target_v = v["vmax"]
            # arrêt au feu rouge si on s'en approche
            dist_light = (a.light_x - v["x"]) * v["dir"]
            if red and 0 < dist_light < 25:
                target_v = 0.0 if dist_light < 5 else min(target_v, dist_light / 3)
            # accélération / freinage bornés
            dv = max(-4.0 * a.dt, min(2.0 * a.dt, target_v - v["v"]))
            v["v"] = max(0.0, v["v"] + dv)
            v["x"] += v["dir"] * v["v"] * a.dt
            if v["x"] >= a.length:
                v["x"], v["dir"] = a.length, -1
            elif v["x"] <= 0:
                v["x"], v["dir"] = 0.0, 1
        t += a.dt
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t", "id", "x", "y"])
        w.writeheader()
        w.writerows(rows)
    print(f"{a.out}: {len(rows)} lignes, {a.n} véhicules, {a.duration} s")


if __name__ == "__main__":
    main()
