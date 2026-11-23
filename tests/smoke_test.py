#!/usr/bin/env python3
"""Test de fumée : lance experiments/smoke.yaml (20 s) et vérifie les résultats.

  python3 tests/smoke_test.py                  # backend sim   (< 5 s)
  python3 tests/smoke_test.py --backend local  # vraies applis sans émulation (~25 s)
  sudo python3 tests/smoke_test.py --backend mininet   # environnement complet (~30 s)

Affiche SMOKE OK en cas de succès (à déposer avant la séance 2).
"""
import argparse
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ubiq import metrics  # noqa: E402
from ubiq.run import main as run_main  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="sim", choices=["sim", "local", "mininet"])
    a = ap.parse_args()
    out = os.path.join(ROOT, "results", "_smoke")
    t0 = time.time()
    run_main(["experiments/smoke.yaml", "--backend", a.backend, "--results", out, "--clean"])
    rd = os.path.join(out, "smoke", "always_edge", "base", "rep0")
    errors = []
    for f in ("tasks.csv", "events.csv", "ticks.csv", "aoi.csv", "meta.json"):
        if not os.path.exists(os.path.join(rd, f)):
            errors.append(f"fichier manquant : {f}")
    if not errors:
        s = {r["phase"]: r for r in metrics.summarize_run(rd)}["all"]
        print(f"  tâches={s['tasks']}  succès={s['success_ratio']:.2f}  latence p95={s['lat_p95_ms']:.0f} ms  "
              f"AoI moyen={s['aoi_mean_ms']:.0f} ms  handovers={s['handovers']}")
        if s["tasks"] < 300:
            errors.append(f"trop peu de tâches ({s['tasks']})")
        if not (s["success_ratio"] > 0.6):
            errors.append(f"taux de succès anormal ({s['success_ratio']:.2f})")
        if not (s["aoi_mean_ms"] < 5000):
            errors.append("AoI anormal (perception en panne ?)")
    print(f"\nmachine={platform.node()}  python={platform.python_version()}  backend={a.backend}  "
          f"durée={time.time() - t0:.0f} s")
    if errors:
        print("SMOKE ÉCHEC :\n  - " + "\n  - ".join(errors))
        sys.exit(1)
    print("SMOKE OK")


if __name__ == "__main__":
    main()
