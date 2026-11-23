"""Backend `sim` : simulation à événements discrets, plus rapide que le temps réel.

Sert à DÉVELOPPER et DÉBOGUER les politiques sur n'importe quel portable.
Les figures finales du projet doivent venir du backend `mininet`.

Modèle (volontairement simple, à discuter dans la section « Limites ») :
  - chaque AP est un serveur FIFO de temps d'antenne (uplink) ;
  - un handover pendant un envoi force une retransmission via le nouvel AP (comme TCP) ;
  - chaque nœud de calcul (Edge, UAV-Edge, Cloud) est une file à k serveurs ;
  - le CPU embarqué est une file à 1 serveur ;
  - l'UAV ajoute une file de backhaul (débit fonction de sa position).
"""
from __future__ import annotations

import heapq
import math
import random
from collections import deque

from .. import metrics
from ..ctx import EdgeLoad, Task
from ..ctxbuild import make_ctx
from ..world import UAV_SITE, World, build_policies


class Sim:
    def __init__(self):
        self.t = 0.0
        self.q: list = []
        self.seq = 0

    def at(self, t: float, fn, *args) -> None:
        heapq.heappush(self.q, (t, self.seq, fn, args))
        self.seq += 1

    def run(self, until: float) -> None:
        while self.q and self.q[0][0] <= until:
            t, _, fn, args = heapq.heappop(self.q)
            self.t = t
            fn(t, *args)


class FifoServer:
    """File FIFO à k serveurs ; planification calculée à l'arrivée."""

    def __init__(self, k: int):
        self.free = [0.0] * max(1, k)
        heapq.heapify(self.free)
        self.jobs: deque = deque()  # (arrivée, fin)

    def submit(self, t_arr: float, service_s: float) -> tuple[float, float]:
        w = heapq.heappop(self.free)
        start = max(t_arr, w)
        end = start + max(service_s, 0.0)
        heapq.heappush(self.free, end)
        self.jobs.append((t_arr, end))
        return start, end

    def in_system(self, t: float) -> int:
        while self.jobs and self.jobs[0][1] <= t and len(self.jobs) > 0:
            # purge approximative (les fins ne sont pas triées, mais presque)
            self.jobs.popleft()
        return sum(1 for a, e in self.jobs if a <= t < e)


class VehicleRT:
    def __init__(self, vid: str):
        self.vid = vid
        self.cpu = FifoServer(1)
        self.pcpu = FifoServer(1)
        self.history: dict[str, deque] = {}
        self.service_loc: str | None = None
        self.migrating_until = 0.0
        self.n_task = 0
        self.n_msg = 0

    def record(self, key: str, t: float, lat: float, status: str) -> None:
        self.history.setdefault(key, deque(maxlen=50)).append((t, lat, status))


def lognormal_factor(rng: random.Random, cv: float) -> float:
    if cv <= 0:
        return 1.0
    s2 = math.log(1 + cv * cv)
    return rng.lognormvariate(-s2 / 2, math.sqrt(s2))


def run_sim(sc: dict, seed: int, run_dir: str, meta: dict) -> None:
    pol = build_policies(sc)
    for p in pol.values():
        p.reset(seed)
    world = World(sc, seed, pol)
    rng = random.Random(seed + 17)
    sim = Sim()
    dur = world.duration
    tasks_cfg = sc["tasks"]
    cv = float(tasks_cfg.get("jitter_cv", 0.1))
    local_ms = float(sc["vehicles"].get("local_service_ms", 100))
    perc_cfg = sc.get("perception") or {}
    serv_cfg = sc.get("service") or {}
    stateful = bool(serv_cfg.get("stateful", False))
    load_period = float(sc.get("load_report_s", 0.5))

    rts = {vid: VehicleRT(vid) for vid in world.veh}
    air = {aid: FifoServer(1) for aid in world.aps}
    nodes = {nid: FifoServer(n["workers"]) for nid, n in world.nodes.items()}
    bh = FifoServer(1)
    reports: dict[str, EdgeLoad] = {}
    task_rows, perc_rows, receipts = [], [], []

    def ctx_of(vid, t):
        rt = rts[vid]
        view = world.vehicle_view(vid, rt.service_loc)
        return make_ctx(view, t, reports, rt.cpu.in_system(t), local_ms, rt.service_loc,
                        t >= rt.migrating_until, rt.history)

    # ------------------------------------------------------------------ tick
    def tick(t):
        world.step(t)
        for vid, v in world.veh.items():
            rt = rts[vid]
            if rt.service_loc is None and v["serving"]:
                rt.service_loc = world.nearest_edge(vid)
            if stateful and rt.service_loc and t >= rt.migrating_until:
                dest = pol["migration"].decide(ctx_of(vid, t))
                if dest and dest != rt.service_loc and dest in world.nodes and world.nodes[dest]["up"]:
                    d = world.graph.path_delay_ms(world.nodes[rt.service_loc]["site"], world.nodes[dest]["site"])
                    if d is not None:
                        bw = float(serv_cfg.get("migration_bw_mbps", 100))
                        down = serv_cfg.get("state_mb", 20) * 8 / bw + (d + serv_cfg.get("migration_fixed_ms", 50)) / 1000
                        rt.migrating_until = t + down
                        world.log_event(t, "migration_start", vid, f"{rt.service_loc}->{dest} downtime={down*1000:.0f}ms")
                        src = rt.service_loc
                        rt.service_loc = dest
                        sim.at(t + down, lambda tt, vid=vid, s=src, d_=dest: world.log_event(tt, "migration_end", vid, f"{s}->{d_}"))
        if t + world.dt <= dur + 1e-9:
            sim.at(round(t + world.dt, 6), tick)

    def report(t):
        for nid, n in world.nodes.items():
            if not n["up"]:
                continue          # un nœud en panne n'envoie plus de rapport : le dernier vieillit
            reports[nid] = EdgeLoad(nodes[nid].in_system(t), n["workers"], n["service_ms"] * n["slowdown"],
                                    n["up"], t)
        if t + load_period <= dur:
            sim.at(t + load_period, report)

    # ------------------------------------------------------------------ tâches
    def finish(t, rec, status, lat=float("nan")):
        rec["t_end"] = round(t, 4)
        rec["status"] = status
        rec["latency_ms"] = round(lat, 2) if lat == lat else ""
        rt = rts[rec["vid"]]
        rt.record(rec["target"], t, lat, status)
        if rec["node"]:
            rt.record("node:" + rec["node"], t, lat, status)

    def gen_task(t, vid):
        rt = rts[vid]
        rt.n_task += 1
        task = Task(f"{vid}-{rt.n_task}", vid, t, float(tasks_cfg["input_kb"]), float(tasks_cfg["output_kb"]),
                    float(tasks_cfg["deadline_ms"]))
        ctx = ctx_of(vid, t)
        target = pol["offloading"].decide(task, ctx)
        if target not in ctx.candidates:
            target = "local"
        rec = {"vid": vid, "task": task.id, "t_gen": round(t, 4), "phase": world.phase_of(t), "target": target,
               "node": "", "ap_at_gen": world.veh[vid]["serving"] or "", "deadline_ms": task.deadline_ms}
        task_rows.append(rec)

        def done(tt):
            lat = (tt - t) * 1000
            finish(tt, rec, "ok" if lat <= task.deadline_ms else "late", lat)

        if target == "local":
            _, e = rt.cpu.submit(t, local_ms * lognormal_factor(rng, cv) / 1000)
            sim.at(e, done)
        else:
            node = world.resolve_target(vid, target, rt.service_loc)
            if node is None:
                finish(t, rec, "fail_no_target")
            elif target == "service" and t < rt.migrating_until:
                finish(t, rec, "fail_migrating")
            else:
                rec["node"] = node
                send_up(t, vid, node, task.input_kb, lambda tt, n=node: at_node(tt, vid, n, rec, "task", done),
                        lambda tt, why: finish(tt, rec, "fail_" + why))
        nxt = t + (1.0 / float(tasks_cfg["rate_hz"])) * rng.uniform(0.9, 1.1)
        if nxt < dur - 1.0:
            sim.at(nxt, gen_task, vid)

    def send_up(t, vid, node, size_kb, on_ok, on_fail, retries=0):
        v = world.veh[vid]
        ap_id = v["serving"]
        if ap_id is None:
            return on_fail(t, "no_coverage")
        rate = world.uplink_rate(vid)
        if rate <= 0:
            return on_fail(t, "no_coverage")
        bits = size_kb * 8e3
        epoch = v["epoch"]
        _, e = air[ap_id].submit(max(t, v["ho_until"]), bits / (rate * 1e6))

        def uplink_done(tt):
            if world.veh[vid]["epoch"] != epoch:
                # handover pendant l'envoi : comme TCP, on retransmet via le nouvel AP (2 fois max)
                if world.veh[vid]["serving"] and retries < 2:
                    return send_up(tt, vid, node, size_kb, on_ok, on_fail, retries + 1)
                return on_fail(tt, "handover")
            ap = world.aps[ap_id]
            if not ap["up"]:
                return on_fail(tt, "ap_down")
            if ap["is_uav"] and world.nodes[node]["site"] != UAV_SITE:
                if world.bh_rate <= 0:
                    return on_fail(tt, "backhaul")
                _, e2 = bh.submit(tt, bits / (world.bh_rate * 1e6))
                sim.at(e2, wired, ap_id)
            else:
                wired(tt, ap_id)

        def wired(tt, ap):
            d = world.node_reachable_delay_ms(ap, node)
            if d is None:
                return on_fail(tt, "unreachable")
            sim.at(tt + d / 1000, on_ok)

        sim.at(e, uplink_done)

    def at_node(t, vid, node, rec, kind, on_delivered, repr_cfg=None):
        n = world.nodes[node]
        if not n["up"]:
            return finish(t, rec, "fail_edge_down") if kind == "task" else perc_fail(t, rec, "edge_down")
        base = n["service_ms"] if kind == "task" else float(repr_cfg["fusion_ms"])
        _, e = nodes[node].submit(t, base * n["slowdown"] * lognormal_factor(rng, cv) / 1000)

        def node_done(tt):
            if not world.nodes[node]["up"]:
                return finish(tt, rec, "fail_edge_down") if kind == "task" else perc_fail(tt, rec, "edge_down")
            if kind == "perc":
                return on_delivered(tt)
            v = world.veh[vid]
            ap = v["serving"]
            d = world.node_reachable_delay_ms(ap, node) if ap else None
            rate = world.uplink_rate(vid)
            if d is None or rate <= 0:
                return finish(tt, rec, "fail_return_lost")
            epoch = v["epoch"]
            tx = float(rec_out_kb) * 8e3 / (rate * 1e6)

            def back(t3):
                if world.veh[vid]["epoch"] != epoch:
                    return finish(t3, rec, "fail_return_lost")
                on_delivered(t3)

            sim.at(tt + d / 1000 + tx, back)

        sim.at(e, node_done)

    rec_out_kb = float(tasks_cfg["output_kb"])

    # ------------------------------------------------------------------ perception
    reprs = perc_cfg.get("reprs") or {}

    def perc_fail(t, rec, why):
        rec["status"] = "fail_" + why
        rec["t_avail"] = ""

    def gen_perc(t, vid):
        rt = rts[vid]
        rt.n_msg += 1
        rep, f = pol["perception"].choose(t, ctx_of(vid, t))
        if rep not in reprs:
            rep = "objects"
        cfg = reprs[rep]
        rec = {"vid": vid, "msg": f"{vid}-p{rt.n_msg}", "t_gen": round(t, 4), "phase": world.phase_of(t),
               "repr": rep, "size_kb": cfg["size_kb"], "node": "", "t_avail": "", "status": "pending",
               "accuracy": cfg.get("accuracy", 1.0)}
        perc_rows.append(rec)
        _, e = rt.pcpu.submit(t, float(cfg.get("pre_ms", 0)) / 1000)

        def after_pre(tt):
            node = world.resolve_target(vid, "edge:nearest")
            if node is None:
                return perc_fail(tt, rec, "no_target")
            rec["node"] = node

            def delivered(t3):
                rec["status"] = "ok"
                rec["t_avail"] = round(t3, 4)
                receipts.append({"vid": vid, "t_gen": t, "t_avail": t3, "accuracy": cfg.get("accuracy", 1.0)})

            send_up(tt, vid, node, float(cfg["size_kb"]),
                    lambda t3: at_node(t3, vid, node, rec, "perc", delivered, cfg),
                    lambda t3, why: perc_fail(t3, rec, why))

        sim.at(e, after_pre)
        nxt = t + 1.0 / max(float(f), 0.05)
        if nxt < dur - 0.5:
            sim.at(nxt, gen_perc, vid)

    # ------------------------------------------------------------------ run
    sim.at(0.0, tick)
    sim.at(0.0, report)
    for vid in world.veh:
        sim.at(rng.uniform(0.2, 0.2 + 1.0 / float(tasks_cfg["rate_hz"])), gen_task, vid)
        if perc_cfg.get("enabled", False):
            sim.at(rng.uniform(0.2, 0.7), gen_perc, vid)
    sim.run(dur + 3.0)

    for r in task_rows:
        if "status" not in r:
            r["status"] = "fail_timeout"
    for r in perc_rows:
        if r["status"] == "pending":
            r["status"] = "fail_timeout"

    aoi_rows, _ = metrics.aoi_samples(receipts, list(world.veh), dur, world.phase_of) if perc_cfg.get("enabled") else ([], {})
    metrics.write_csv(f"{run_dir}/tasks.csv", task_rows, metrics.TASK_FIELDS)
    metrics.write_csv(f"{run_dir}/perception.csv", perc_rows, metrics.PERC_FIELDS)
    metrics.write_csv(f"{run_dir}/aoi.csv", aoi_rows, metrics.AOI_FIELDS)
    metrics.write_csv(f"{run_dir}/ticks.csv", world.tick_rows, metrics.TICK_FIELDS)
    metrics.write_csv(f"{run_dir}/events.csv", world.event_rows, metrics.EVENT_FIELDS)
    metrics.write_csv(f"{run_dir}/uav.csv", world.uav_rows, metrics.UAV_FIELDS)
    meta = dict(meta)
    meta.update({"backend": "sim", "phases": world.phases, "vehicles": list(world.veh)})
    metrics.dump_meta(run_dir, meta)
