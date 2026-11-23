"""Agent embarqué d'un véhicule -- backend Mininet (tourne DANS la station).

  python3 -m ubiq.apps.vehicle_agent --rt <dossier> --vid V1 --seed 1001

- génère des tâches périodiques, appelle la politique d'offloading,
  exécute en local (CPU émulé, file FIFO) ou envoie en TCP à un nœud ;
- génère les mises à jour de perception (politique de perception) ;
- appelle la politique de migration (services avec état) ;
- lit l'état publié par le contrôleur (<rt>/state.json) et les rapports
  de charge des nœuds (<rt>/load_*.json) : mêmes informations que dans le
  backend sim, avec les mêmes retards.
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import queue
import random
import socket
import sys
import threading
import time
from collections import deque

from .proto import PORT, read_json, recv_line, recv_payload, send_msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rt", required=True)
    ap.add_argument("--vid", required=True)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    repo = read_json(os.path.join(a.rt, "repo.json"))["root"]
    sys.path.insert(0, repo)
    from ubiq.ctxbuild import make_ctx
    from ubiq.ctx import Task
    from ubiq.world import build_policies
    from ubiq.metrics import PERC_FIELDS, TASK_FIELDS, EVENT_FIELDS

    sc = read_json(os.path.join(a.rt, "scenario.json"))
    ips = read_json(os.path.join(a.rt, "ips.json"))
    pol = build_policies(sc)
    for p in pol.values():
        p.reset(a.seed)
    rng = random.Random(a.seed)
    tasks_cfg = sc["tasks"]
    cv = float(tasks_cfg.get("jitter_cv", 0.1))
    local_ms = float(sc["vehicles"].get("local_service_ms", 100))
    perc_cfg = sc.get("perception") or {}
    reprs = perc_cfg.get("reprs") or {}
    serv = sc.get("service") or {}
    stateful = bool(serv.get("stateful", False))
    dur = float(sc["duration_s"])
    phases = sc.get("phases") or [{"name": "all", "start": 0, "end": dur}]

    def phase_of(t):
        for p in phases:
            if p["start"] <= t < p["end"]:
                return p["name"]
        return phases[-1]["name"]

    def jit():
        if cv <= 0:
            return 1.0
        s2 = math.log(1 + cv * cv)
        return rng.lognormvariate(-s2 / 2, math.sqrt(s2))

    # attendre le démarrage
    st = None
    while st is None or "t0" not in st:
        st = read_json(os.path.join(a.rt, "state.json"))
        time.sleep(0.05)
    t0 = st["t0"]

    def now():
        return time.time() - t0

    lock = threading.Lock()
    task_rows, perc_rows, ev_rows = [], [], []
    history: dict[str, deque] = {}
    S = {"service_loc": None, "migrating_until": 0.0, "n": 0, "m": 0, "local_q": 0}

    def record(key, t, lat, status):
        with lock:
            history.setdefault(key, deque(maxlen=50)).append((t, lat, status))

    def state():
        return read_json(os.path.join(a.rt, "state.json"), st)

    def loads():
        out = {}
        for f in glob.glob(os.path.join(a.rt, "load_*.json")):
            d = read_json(f)
            if d:
                out[os.path.basename(f)[5:-5]] = d
        return out

    def ctx_now():
        s = state()
        view = dict(s["views"][a.vid])
        if S["service_loc"] and "service" in view["candidates"]:
            d = view["node_delay_ms"].get(S["service_loc"])
            view["path_delay_ms"]["service"] = d if d is not None else float("inf")
        return make_ctx(view, now(), loads(), S["local_q"], local_ms, S["service_loc"],
                        now() >= S["migrating_until"], history), view

    def finish(rec, status, lat=float("nan")):
        t = now()
        rec["t_end"] = round(t, 4)
        rec["status"] = status
        rec["latency_ms"] = round(lat, 2) if lat == lat else ""
        record(rec["target"], t, lat, status)
        if rec["node"]:
            record("node:" + rec["node"], t, lat, status)

    # --- CPU embarqué (tâches) et unité de prétraitement (perception) -------
    cpu_q: queue.Queue = queue.Queue()
    pcpu_q: queue.Queue = queue.Queue()

    def cpu_worker(q, is_cpu):
        while True:
            ms, cb = q.get()
            time.sleep(ms / 1000.0)
            if is_cpu:
                S["local_q"] -= 1
            cb()

    threading.Thread(target=cpu_worker, args=(cpu_q, True), daemon=True).start()
    threading.Thread(target=cpu_worker, args=(pcpu_q, False), daemon=True).start()

    def remote_call(node, header, size_kb, timeout_s):
        addr = str(ips[node])
        ip, port = (addr.rsplit(":", 1)[0], int(addr.rsplit(":", 1)[1])) if ":" in addr else (addr, PORT)
        with socket.create_connection((ip, port), timeout=timeout_s) as s:
            s.settimeout(timeout_s)
            send_msg(s, header, int(size_kb * 1000))
            f = s.makefile("rb")
            h = recv_line(f)
            if h is None:
                raise ConnectionError("pas de réponse")
            recv_payload(f, int(h["size"]))

    # --- tâches ---------------------------------------------------------------
    def resolve(target, view):
        if target == "cloud":
            return "cloud"
        if target == "service":
            return S["service_loc"]
        if target == "edge:nearest":
            return view["nearest_edge"]
        if target.startswith("edge:"):
            return target[5:]
        return None

    def task_loop():
        period = 1.0 / float(tasks_cfg["rate_hz"])
        t_next = rng.uniform(0.2, 0.2 + period)
        while t_next < dur - 1.0:
            time.sleep(max(0.0, t_next - now()))
            t = now()
            S["n"] += 1
            task = Task(f"{a.vid}-{S['n']}", a.vid, t, float(tasks_cfg["input_kb"]),
                        float(tasks_cfg["output_kb"]), float(tasks_cfg["deadline_ms"]))
            ctx, view = ctx_now()
            try:
                target = pol["offloading"].decide(task, ctx)
            except Exception as e:  # une politique qui plante ne doit pas tuer l'agent
                print(f"[{a.vid}] erreur politique offloading : {e!r}", file=sys.stderr, flush=True)
                target = "local"
            if target not in ctx.candidates:
                target = "local"
            rec = {"vid": a.vid, "task": task.id, "t_gen": round(t, 4), "phase": phase_of(t), "target": target,
                   "node": "", "ap_at_gen": view["serving"] or "", "deadline_ms": task.deadline_ms}
            with lock:
                task_rows.append(rec)

            if target == "local":
                S["local_q"] += 1

                def done_local(rec=rec, t=t, dl=task.deadline_ms):
                    lat = (now() - t) * 1000
                    finish(rec, "ok" if lat <= dl else "late", lat)
                cpu_q.put((local_ms * jit(), done_local))
            else:
                node = resolve(target, view)
                if node is None or node not in ips:
                    finish(rec, "fail_no_target")
                elif target == "service" and t < S["migrating_until"]:
                    finish(rec, "fail_migrating")
                else:
                    rec["node"] = node

                    def run_remote(rec=rec, node=node, t=t, dl=task.deadline_ms):
                        try:
                            remote_call(node, {"kind": "task", "vid": a.vid, "id": rec["task"],
                                               "t_gen": t, "out_kb": tasks_cfg["output_kb"]},
                                        float(tasks_cfg["input_kb"]), max(1.0, 4 * dl / 1000))
                            lat = (now() - t) * 1000
                            finish(rec, "ok" if lat <= dl else "late", lat)
                        except socket.timeout:
                            finish(rec, "fail_timeout")
                        except OSError:
                            finish(rec, "fail_conn")
                    threading.Thread(target=run_remote, daemon=True).start()
            t_next += period * rng.uniform(0.9, 1.1)

    # --- perception -----------------------------------------------------------
    def perc_loop():
        t_next = rng.uniform(0.2, 0.7)
        while t_next < dur - 0.5:
            time.sleep(max(0.0, t_next - now()))
            t = now()
            S["m"] += 1
            ctx, view = ctx_now()
            try:
                rep, f = pol["perception"].choose(t, ctx)
            except Exception as e:
                print(f"[{a.vid}] erreur politique perception : {e!r}", file=sys.stderr, flush=True)
                rep, f = "objects", 1.0
            if rep not in reprs:
                rep = "objects"
            cfg = reprs[rep]
            rec = {"vid": a.vid, "msg": f"{a.vid}-p{S['m']}", "t_gen": round(t, 4), "phase": phase_of(t),
                   "repr": rep, "size_kb": cfg["size_kb"], "node": "", "t_avail": "", "status": "pending",
                   "accuracy": cfg.get("accuracy", 1.0)}
            with lock:
                perc_rows.append(rec)

            def after_pre(rec=rec, cfg=cfg, t=t):
                node = state()["views"][a.vid]["nearest_edge"]
                if node is None or node not in ips:
                    rec["status"] = "fail_no_target"
                    return
                rec["node"] = node

                def send():
                    try:
                        remote_call(node, {"kind": "perc", "vid": a.vid, "id": rec["msg"], "t_gen": t,
                                           "fusion_ms": cfg["fusion_ms"], "accuracy": cfg.get("accuracy", 1.0)},
                                    float(cfg["size_kb"]), 2.0)
                        rec["status"] = "ok"
                        rec["t_avail"] = round(now(), 4)
                    except socket.timeout:
                        rec["status"] = "fail_timeout"
                    except OSError:
                        rec["status"] = "fail_conn"
                threading.Thread(target=send, daemon=True).start()
            pcpu_q.put((float(cfg.get("pre_ms", 0)), after_pre))
            t_next += 1.0 / max(float(f), 0.05)

    # --- migration (services avec état) ----------------------------------------
    def mig_loop():
        while now() < dur:
            s = state()
            view = s["views"][a.vid]
            if S["service_loc"] is None and view["serving"]:
                S["service_loc"] = view["nearest_edge"]
            if stateful and S["service_loc"] and now() >= S["migrating_until"]:
                ctx, _ = ctx_now()
                try:
                    dest = pol["migration"].decide(ctx)
                except Exception as e:
                    print(f"[{a.vid}] erreur politique migration : {e!r}", file=sys.stderr, flush=True)
                    dest = None
                d = (s.get("node_pair_delay_ms") or {}).get(S["service_loc"], {}).get(dest) if dest else None
                if dest and dest != S["service_loc"] and dest in ips and d is not None:
                    bw = float(serv.get("migration_bw_mbps", 100))
                    down = serv.get("state_mb", 20) * 8 / bw + (d + serv.get("migration_fixed_ms", 50)) / 1000
                    t = now()
                    ev_rows.append({"t": round(t, 4), "type": "migration_start", "target": a.vid,
                                    "detail": f"{S['service_loc']}->{dest} downtime={down * 1000:.0f}ms"})
                    S["migrating_until"] = t + down
                    S["service_loc"] = dest
            time.sleep(float(sc.get("tick_s", 0.1)))

    ths = [threading.Thread(target=task_loop, daemon=True), threading.Thread(target=mig_loop, daemon=True)]
    if perc_cfg.get("enabled", False):
        ths.append(threading.Thread(target=perc_loop, daemon=True))
    for th in ths:
        th.start()
    while now() < dur + 3.0 and not os.path.exists(os.path.join(a.rt, "STOP")):
        time.sleep(0.2)

    for r in task_rows:
        r.setdefault("status", "fail_timeout")
    for r in perc_rows:
        if r["status"] == "pending":
            r["status"] = "fail_timeout"
    for name, rows, fields in (("tasks", task_rows, TASK_FIELDS), ("perc", perc_rows, PERC_FIELDS),
                               ("events", ev_rows, EVENT_FIELDS)):
        with open(os.path.join(a.rt, f"agent_{a.vid}_{name}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    print(f"[vehicle_agent] {a.vid} terminé : {len(task_rows)} tâches", flush=True)


if __name__ == "__main__":
    main()
