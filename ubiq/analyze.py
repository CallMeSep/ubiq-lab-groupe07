"""Analyse d'une expérience : tableaux + figures standard.

  python3 -m ubiq.analyze experiments/baseline.yaml
  python3 -m ubiq.analyze experiments/group_07.yaml --metric lat_p95_ms --phase uav

Produit dans results/<exp>/ :
  summary_runs.csv   une ligne par (run, phase)
  summary.csv        moyenne + IC 95 % par (variante, valeur balayée, phase)
  figures/fig_phases.pdf     indicateurs par phase et par variante   (figure « baseline / comparaison »)
  figures/fig_sweep.pdf      indicateur vs paramètre balayé           (si balayage)
  figures/fig_timeline.pdf   évolution temporelle (rep 0)             (lecture fine)
  figures/fig_uav.pdf        altitude, véhicules servis, puissance    (si UAV)
"""
from __future__ import annotations

import argparse
import glob
import math
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import metrics  # noqa: E402
from .config import REPO_ROOT, load_experiment  # noqa: E402

# Palette catégorielle (ordre fixe, jamais recyclé) -- validée daltonisme
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
PHASE_BG = ["#f4f4f2", "#fbeee8", "#eaf4ef", "#f2f0fa"]

METRIC_LABELS = {
    "success_ratio": "Taux de succès (échéance respectée)",
    "fail_ratio": "Taux d'échec",
    "lat_mean_ms": "Latence moyenne (ms)",
    "lat_p95_ms": "Latence p95 (ms)",
    "aoi_mean_ms": "AoI moyen (ms)",
    "aoi_p95_ms": "AoI p95 (ms)",
    "perc_accuracy_mean": "Précision moyenne livrée",
    "uav_energy_kj": "Énergie UAV (kJ)",
    "handovers": "Nombre de handovers",
    "migrations": "Nombre de migrations",
    "share_local": "Part de tâches locales",
}

T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
       15: 2.13, 20: 2.09, 30: 2.04}


def t95(n: int) -> float:
    if n <= 1:
        return float("nan")
    df = n - 1
    keys = sorted(T95)
    for k in keys:
        if df <= k:
            return T95[k]
    return 1.96


def mean_ci(vals):
    v = [x for x in vals if x == x]
    n = len(v)
    if n == 0:
        return float("nan"), float("nan"), 0
    m = sum(v) / n
    if n == 1:
        return m, float("nan"), 1
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return m, t95(n) * sd / math.sqrt(n), n


def style(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.yaxis.label.set_color(INK)
    ax.xaxis.label.set_color(INK)


def collect(exp_name: str, results: str):
    runs = sorted(glob.glob(os.path.join(results, exp_name, "*", "*", "rep*")))
    rows = []
    for rd in runs:
        if os.path.exists(os.path.join(rd, "meta.json")):
            for r in metrics.summarize_run(rd):
                r["run_dir"] = os.path.relpath(rd, REPO_ROOT)
                rows.append(r)
    return runs, rows


def aggregate(rows, keys=("variant", "sweep_value", "phase")):
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in keys)].append(r)
    out = []
    for k, rs in groups.items():
        d = dict(zip(keys, k))
        d["reps"] = len(rs)
        for m in METRIC_LABELS:
            mu, ci, _ = mean_ci([float(r[m]) for r in rs])
            d[m] = mu
            d[m + "_ci95"] = ci
        out.append(d)
    return out


def fig_phases(agg, variants, phases, metrics_list, path):
    fig, axes = plt.subplots(1, len(metrics_list), figsize=(4.2 * len(metrics_list), 3.4))
    if len(metrics_list) == 1:
        axes = [axes]
    w = 0.8 / max(1, len(variants))
    for ax, m in zip(axes, metrics_list):
        for i, v in enumerate(variants):
            ys, es = [], []
            for ph in phases:
                row = next((a for a in agg if a["variant"] == v and a["phase"] == ph), None)
                ys.append(row[m] if row else float("nan"))
                es.append(row[m + "_ci95"] if row else float("nan"))
            xs = [j + (i - (len(variants) - 1) / 2) * w for j in range(len(phases))]
            ax.bar(xs, ys, width=w * 0.92, color=SERIES[i % len(SERIES)], label=v,
                   yerr=[e if e == e else 0 for e in es], error_kw={"elinewidth": 1, "capsize": 2, "ecolor": INK2})
        ax.set_xticks(range(len(phases)))
        ax.set_xticklabels(phases)
        ax.set_title(METRIC_LABELS.get(m, m), fontsize=9, color=INK)
        style(ax)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=min(len(l), 6), fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(path)
    fig.savefig(path.replace(".pdf", ".png"), dpi=150)
    plt.close(fig)


def fig_sweep(agg, variants, param, phase, metric, path):
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for i, v in enumerate(variants):
        pts = sorted([a for a in agg if a["variant"] == v and a["phase"] == phase],
                     key=lambda a: float(a["sweep_value"]))
        xs = [float(a["sweep_value"]) for a in pts]
        ys = [a[metric] for a in pts]
        es = [a[metric + "_ci95"] if a[metric + "_ci95"] == a[metric + "_ci95"] else 0 for a in pts]
        ax.errorbar(xs, ys, yerr=es, color=SERIES[i % len(SERIES)], marker="o", markersize=4, linewidth=2,
                    capsize=2, label=v)
    allv = [a[metric] for a in agg if a["phase"] == phase and a[metric] == a[metric] and a[metric] > 0]
    if metric.startswith(("lat", "aoi")) and allv and max(allv) / max(min(allv), 1e-9) > 30:
        ax.set_yscale("log")          # effondrements : échelle log pour garder les petites valeurs lisibles
    ax.set_xlabel(param)
    ax.set_ylabel(METRIC_LABELS.get(metric, metric))
    ax.set_title(f"phase : {phase}", fontsize=9, color=INK2)
    style(ax)
    ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    fig.savefig(path.replace(".pdf", ".png"), dpi=150)
    plt.close(fig)


def shade_phases(ax, phases_meta):
    for k, p in enumerate(phases_meta):
        ax.axvspan(p["start"], p["end"], color=PHASE_BG[k % len(PHASE_BG)], zorder=0)


def fig_timeline(exp_name, results, variants, path, bin_s=2.0):
    import json
    fig, axes = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    phases_meta = None
    for i, v in enumerate(variants):
        rds = sorted(glob.glob(os.path.join(results, exp_name, v, "*", "rep0")))
        if not rds:
            continue
        rd = rds[0]
        meta = json.load(open(os.path.join(rd, "meta.json")))
        phases_meta = meta["phases"]
        tasks = metrics.read_csv(os.path.join(rd, "tasks.csv"))
        dur = phases_meta[-1]["end"]
        nb = int(dur / bin_s) + 1
        tot, ok = [0] * nb, [0] * nb
        lat = [[] for _ in range(nb)]
        for r in tasks:
            b = int(float(r["t_gen"]) / bin_s)
            if b >= nb:
                continue
            tot[b] += 1
            ok[b] += r["status"] == "ok"
            if r["latency_ms"] not in ("", None):
                lat[b].append(float(r["latency_ms"]))
        xs = [(b + 0.5) * bin_s for b in range(nb)]
        axes[0].plot(xs, [ok[b] / tot[b] if tot[b] else float("nan") for b in range(nb)],
                     color=SERIES[i % len(SERIES)], linewidth=1.6, label=v)
        axes[1].plot(xs, [metrics.percentile(lat[b], 0.95) for b in range(nb)],
                     color=SERIES[i % len(SERIES)], linewidth=1.6, label=v)
    if phases_meta:
        for ax in axes:
            shade_phases(ax, phases_meta)
            style(ax)
        for p in phases_meta:
            axes[0].text((p["start"] + p["end"]) / 2, 1.02, p["name"], ha="center", fontsize=8, color=INK2)
    axes[0].set_ylabel("succès (fenêtre 2 s)")
    axes[0].set_ylim(0, 1.08)
    axes[1].set_ylabel("latence p95 (ms)")
    axes[1].set_xlabel("temps (s)")
    axes[0].legend(fontsize=7, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(path)
    fig.savefig(path.replace(".pdf", ".png"), dpi=150)
    plt.close(fig)


def fig_uav(exp_name, results, variants, path):
    import json
    data = []
    for i, v in enumerate(variants):
        rds = sorted(glob.glob(os.path.join(results, exp_name, v, "*", "rep0")))
        if not rds:
            continue
        rows = metrics.read_csv(os.path.join(rds[0], "uav.csv"))
        if rows and any(float(r["h"]) > 0 for r in rows):
            data.append((i, v, rows, json.load(open(os.path.join(rds[0], "meta.json")))["phases"]))
    if not data:
        return False
    fig, axes = plt.subplots(3, 1, figsize=(8, 6), sharex=True)
    for i, v, rows, ph in data:
        t = [float(r["t"]) for r in rows]
        c = SERIES[i % len(SERIES)]
        axes[0].plot(t, [float(r["h"]) for r in rows], color=c, linewidth=1.6, label=v)
        axes[1].plot(t, [float(r["n_served"]) for r in rows], color=c, linewidth=1.6, label=v)
        axes[2].plot(t, [float(r["power_w"]) for r in rows], color=c, linewidth=1.6, label=v)
    for ax in axes:
        shade_phases(ax, data[0][3])
        style(ax)
    axes[0].set_ylabel("altitude (m)")
    axes[1].set_ylabel("véhicules servis")
    axes[2].set_ylabel("puissance (W)")
    axes[2].set_xlabel("temps (s)")
    axes[0].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    fig.savefig(path.replace(".pdf", ".png"), dpi=150)
    plt.close(fig)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment")
    ap.add_argument("--results", default=os.path.join(REPO_ROOT, "results"))
    ap.add_argument("--metrics", default="success_ratio,lat_p95_ms,aoi_mean_ms",
                    help="indicateurs de fig_phases (séparés par des virgules)")
    ap.add_argument("--metric", default="success_ratio", help="indicateur de fig_sweep")
    ap.add_argument("--phase", default="all", help="phase de fig_sweep")
    a = ap.parse_args(argv)

    exp, _ = load_experiment(a.experiment)
    name = exp["name"]
    runs, rows = collect(name, a.results)
    if not rows:
        raise SystemExit(f"Aucun résultat dans {a.results}/{name} : lancez d'abord python3 -m ubiq.run {a.experiment}")
    out = os.path.join(a.results, name)
    figdir = os.path.join(out, "figures")
    os.makedirs(figdir, exist_ok=True)
    fields = list(rows[0].keys())
    metrics.write_csv(os.path.join(out, "summary_runs.csv"), rows, fields)
    agg = aggregate(rows)
    metrics.write_csv(os.path.join(out, "summary.csv"), agg, list(agg[0].keys()))

    variants = [v for v in exp["variants"] if any(r["variant"] == v for r in rows)]
    import json
    phases = [p["name"] for p in json.load(open(os.path.join(runs[0], "meta.json")))["phases"]]
    mlist = [m for m in a.metrics.split(",") if m]
    if exp.get("sweep"):
        fig_sweep(agg, variants, exp["sweep"]["param"], a.phase, a.metric, os.path.join(figdir, "fig_sweep.pdf"))
        # fig_phases sur la valeur médiane du balayage
        vals = sorted({r["sweep_value"] for r in agg}, key=float)
        mid = vals[len(vals) // 2]
        agg_mid = [r for r in agg if r["sweep_value"] == mid]
        fig_phases(agg_mid, variants, phases, mlist, os.path.join(figdir, "fig_phases.pdf"))
    else:
        fig_phases(agg, variants, phases, mlist, os.path.join(figdir, "fig_phases.pdf"))
    fig_timeline(name, a.results, variants, os.path.join(figdir, "fig_timeline.pdf"))
    has_uav = fig_uav(name, a.results, variants, os.path.join(figdir, "fig_uav.pdf"))

    # tableau console
    print(f"\n== {name} : {len(runs)} runs ==")
    hdr = f"{'variante':<18}{'balayage':<10}{'phase':<10}{'reps':>4} {'succès':>14} {'lat p95 (ms)':>16} {'AoI (ms)':>14}"
    print(hdr)
    print("-" * len(hdr))
    def num(x):
        try:
            return (0, float(x))
        except (TypeError, ValueError):
            return (1, str(x))
    for r in sorted(agg, key=lambda r: (variants.index(r["variant"]) if r["variant"] in variants else 99,
                                        num(r["sweep_value"]), phases.index(r["phase"]) if r["phase"] in phases else 99)):
        def f(m, p=2):
            mu, ci = r[m], r[m + "_ci95"]
            return f"{mu:.{p}f}" + (f" ±{ci:.{p}f}" if ci == ci else "")
        print(f"{r['variant']:<18}{str(r['sweep_value']):<10}{r['phase']:<10}{r['reps']:>4} {f('success_ratio'):>14} "
              f"{f('lat_p95_ms', 0):>16} {f('aoi_mean_ms', 0):>14}")
    print(f"\nFigures : {os.path.relpath(figdir, REPO_ROOT)}/ (fig_phases, fig_timeline"
          f"{', fig_sweep' if exp.get('sweep') else ''}{', fig_uav' if has_uav else ''})")


if __name__ == "__main__":
    main()
