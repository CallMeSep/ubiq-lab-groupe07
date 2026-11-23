"""Lance une expérience : variantes x balayage x répétitions.

  python3 -m ubiq.run experiments/baseline.yaml                 # backend sim
  sudo python3 -m ubiq.run experiments/baseline.yaml --backend mininet
  python3 -m ubiq.run experiments/baseline.yaml --only always_edge --reps 1
  python3 -m ubiq.run experiments/baseline.yaml --backend local        # vraies applis, sans émulation réseau

Résultats : results/<expérience>/<variante>/<valeur_balayage>/rep<k>/
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

from .config import REPO_ROOT, expand_runs, load_experiment


def run_dir_for(exp_name: str, run: dict, root: str) -> str:
    sv = "base" if run["sweep_value"] is None else f"{run['sweep_param'].split('.')[-1]}={run['sweep_value']}"
    return os.path.join(root, exp_name, run["variant"], sv, f"rep{run['rep']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment")
    ap.add_argument("--backend", choices=["sim", "local", "mininet"], default=None)
    ap.add_argument("--reps", type=int, default=None, help="surcharge le nombre de répétitions")
    ap.add_argument("--only", default=None, help="ne lancer qu'une variante")
    ap.add_argument("--duration", type=float, default=None, help="surcharge duration_s (tests rapides)")
    ap.add_argument("--results", default=os.path.join(REPO_ROOT, "results"))
    ap.add_argument("--clean", action="store_true", help="efface les résultats existants de l'expérience")
    ap.add_argument("--cli", action="store_true", help="(mininet) ouvre la CLI Mininet au lieu de lancer les applis")
    a = ap.parse_args(argv)

    sys.path.insert(0, REPO_ROOT)
    exp, scenario = load_experiment(a.experiment)
    if a.reps is not None:
        exp["reps"] = a.reps
    if a.duration is not None:
        scenario["duration_s"] = a.duration
    backend = a.backend or exp.get("backend", "sim")
    runs = expand_runs(exp, scenario)
    if a.only:
        runs = [r for r in runs if r["variant"] == a.only]
    out_root = os.path.join(a.results, exp["name"])
    if a.clean and os.path.isdir(out_root):
        shutil.rmtree(out_root)

    if backend == "sim":
        from .sim.backend import run_sim as runner
    elif backend == "local":
        from .mn.controller import run_local as runner
    else:
        if os.geteuid() != 0:
            raise SystemExit("Le backend mininet doit être lancé avec sudo.")
        from .mn.backend import run_mininet as runner

    print(f"[ubiq] expérience '{exp['name']}' : {len(runs)} run(s), backend={backend}")
    t0 = time.time()
    for i, r in enumerate(runs, 1):
        rd = run_dir_for(exp["name"], r, a.results)
        meta = {"experiment": exp["name"], "variant": r["variant"], "sweep_param": r["sweep_param"],
                "sweep_value": r["sweep_value"], "rep": r["rep"], "seed": r["seed"],
                "policies": r["scenario"].get("policies")}
        t1 = time.time()
        if backend in ("mininet", "local"):
            runner(r["scenario"], r["seed"], rd, meta, cli=a.cli)
        else:
            runner(r["scenario"], r["seed"], rd, meta)
        print(f"  [{i}/{len(runs)}] {r['variant']:<18} sweep={r['sweep_value']!s:<8} rep={r['rep']}  "
              f"-> {os.path.relpath(rd, REPO_ROOT)}  ({time.time() - t1:.1f} s)")
    print(f"[ubiq] terminé en {time.time() - t0:.1f} s. Analyse : python3 -m ubiq.analyze {a.experiment}")


if __name__ == "__main__":
    main()
