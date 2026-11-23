"""Écriture des journaux et calcul des métriques (communs aux deux backends).

Fichiers produits par run (results/<exp>/<variant>/<sweep>/rep<k>/) :
  tasks.csv       une ligne par tâche (latence, statut, cible, phase)
  perception.csv  une ligne par mise à jour de perception
  aoi.csv         âge de l'information par véhicule (échantillonné)
  ticks.csv       positions / AP servant / SNR / débit (toutes les 0,5 s)
  events.csv      pannes, handovers, migrations, UAV...
  uav.csv         trajectoire, puissance, énergie de l'UAV
  meta.json       paramètres du run
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict

TASK_FIELDS = ["vid", "task", "t_gen", "phase", "target", "node", "ap_at_gen", "t_end", "latency_ms",
               "deadline_ms", "status"]
PERC_FIELDS = ["vid", "msg", "t_gen", "phase", "repr", "size_kb", "node", "t_avail", "status", "accuracy"]
AOI_FIELDS = ["t", "phase", "vid", "aoi_ms", "accuracy"]
TICK_FIELDS = ["t", "vid", "x", "y", "serving", "snr_db", "rate_mbps"]
EVENT_FIELDS = ["t", "type", "target", "detail"]
UAV_FIELDS = ["t", "x", "y", "h", "v_h", "power_w", "energy_j", "ap_up", "backhaul_mbps", "n_served"]


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def aoi_samples(receipts: list[dict], vids: list[str], duration: float, phase_of, step: float = 0.1,
                keep_every: int = 5) -> tuple[list[dict], dict]:
    """AoI(t) = t - t_gen de la dernière mise à jour DISPONIBLE (t_avail <= t).

    Renvoie (lignes échantillonnées pour aoi.csv, moyennes {(vid, phase): (somme, n)}).
    Avant la première réception, l'âge est compté depuis t = 0.
    """
    by_vid = defaultdict(list)
    for r in receipts:
        by_vid[r["vid"]].append((float(r["t_avail"]), float(r["t_gen"]), float(r.get("accuracy", 1.0))))
    rows, acc = [], defaultdict(lambda: [0.0, 0])
    n = int(duration / step)
    for vid in vids:
        rec = sorted(by_vid.get(vid, []))
        j, last_gen, last_acc = 0, 0.0, 0.0
        for i in range(n + 1):
            t = i * step
            while j < len(rec) and rec[j][0] <= t:
                if rec[j][1] >= last_gen:
                    last_gen, last_acc = rec[j][1], rec[j][2]
                j += 1
            aoi = (t - last_gen) * 1000.0
            ph = phase_of(t)
            acc[(vid, ph)][0] += aoi
            acc[(vid, ph)][1] += 1
            if i % keep_every == 0:
                rows.append({"t": round(t, 3), "phase": ph, "vid": vid, "aoi_ms": round(aoi, 1),
                             "accuracy": last_acc})
    return rows, acc


def percentile(vals: list[float], q: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = (len(s) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def summarize_run(run_dir: str) -> list[dict]:
    """Une ligne par phase (+ 'all') avec les indicateurs principaux."""
    meta = json.load(open(os.path.join(run_dir, "meta.json")))
    tasks = read_csv(os.path.join(run_dir, "tasks.csv"))
    aoi = read_csv(os.path.join(run_dir, "aoi.csv"))
    perc = read_csv(os.path.join(run_dir, "perception.csv"))
    events = read_csv(os.path.join(run_dir, "events.csv"))
    uav = read_csv(os.path.join(run_dir, "uav.csv"))
    phases = [p["name"] for p in meta["phases"]] + ["all"]
    out = []
    for ph in phases:
        tk = [r for r in tasks if ph == "all" or r["phase"] == ph]
        n = len(tk)
        ok = [r for r in tk if r["status"] == "ok"]
        done = [float(r["latency_ms"]) for r in tk if r["status"] in ("ok", "late")]
        fails = [r for r in tk if r["status"].startswith("fail")]
        ao = [float(r["aoi_ms"]) for r in aoi if ph == "all" or r["phase"] == ph]
        pc = [r for r in perc if ph == "all" or r["phase"] == ph]
        p_ok = [r for r in pc if r["status"] == "ok"]
        pr = next((p for p in meta["phases"] if p["name"] == ph), None)
        in_ph = (lambda t: True) if pr is None else (lambda t: pr["start"] <= t < pr["end"])
        ho = [e for e in events if e["type"] == "handover" and in_ph(float(e["t"]))]
        mig = [e for e in events if e["type"] == "migration_start" and in_ph(float(e["t"]))]
        uv = [r for r in uav if in_ph(float(r["t"]))]
        e_uav = (float(uv[-1]["energy_j"]) - float(uv[0]["energy_j"])) if len(uv) > 1 else 0.0
        by_target = defaultdict(int)
        for r in tk:
            by_target[r["target"]] += 1
        out.append({
            "variant": meta["variant"], "sweep_param": meta.get("sweep_param") or "",
            "sweep_value": meta.get("sweep_value") if meta.get("sweep_value") is not None else "",
            "rep": meta["rep"], "phase": ph,
            "tasks": n,
            "success_ratio": len(ok) / n if n else float("nan"),
            "fail_ratio": len(fails) / n if n else float("nan"),
            "lat_mean_ms": sum(done) / len(done) if done else float("nan"),
            "lat_p50_ms": percentile(done, 0.5),
            "lat_p95_ms": percentile(done, 0.95),
            "aoi_mean_ms": sum(ao) / len(ao) if ao else float("nan"),
            "aoi_p95_ms": percentile(ao, 0.95),
            "perc_delivery_ratio": len(p_ok) / len(pc) if pc else float("nan"),
            "perc_accuracy_mean": (sum(float(r["accuracy"]) for r in p_ok) / len(p_ok)) if p_ok else float("nan"),
            "handovers": len(ho),
            "migrations": len(mig),
            "uav_energy_kj": e_uav / 1000.0,
            "share_local": by_target.get("local", 0) / n if n else float("nan"),
        })
    return out


def dump_meta(run_dir: str, meta: dict) -> None:
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
