"""Contrôleur temps réel commun aux backends `mininet` et `local`.

Boucle (MAPE-K, toutes les tick_s secondes) :
  Monitor  : le monde avance (positions, pannes, UAV)        -> World.step()
  Analyze  : politiques réseau (association, UAV)             -> dans World.step()
  Plan/Exec: application au réseau émulé                      -> adapter.apply()
  Knowledge: publication de l'état pour les agents véhicules  -> state.json

Les applications (vehicle_agent, edge_server) sont de vrais processus qui
échangent de vrais paquets. Un « adapter » décide où elles tournent :
  - MininetAdapter (mn/backend.py) : dans les nœuds Mininet-WiFi ;
  - LocalAdapter   (ci-dessous)    : sur la machine, sans émulation réseau
    (sert à tester les applis et les politiques sans Mininet).
"""
from __future__ import annotations

import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import time

from .. import metrics
from ..apps.proto import PORT, write_json_atomic
from ..config import REPO_ROOT
from ..world import World, build_policies


class BaseAdapter:
    def build(self, ctl: "Controller") -> dict:
        """Construit le réseau ; renvoie {nœud: 'ip' ou 'ip:port'}."""
        raise NotImplementedError

    def start_server(self, ctl, node: dict, cmd: list[str]) -> None:
        raise NotImplementedError

    def start_agent(self, ctl, vid: str, cmd: list[str]) -> None:
        raise NotImplementedError

    def apply(self, ctl, changes) -> None:
        """Applique l'état courant du monde au réseau émulé."""

    def cli(self, ctl) -> None:
        pass

    def stop(self, ctl) -> None:
        raise NotImplementedError


class LocalAdapter(BaseAdapter):
    """Tout sur localhost, un port par nœud, aucune émulation réseau."""

    def __init__(self):
        self.procs: list[subprocess.Popen] = []

    def build(self, ctl):
        return {nid: f"127.0.0.1:{PORT + 1 + i}" for i, nid in enumerate(sorted(ctl.world.nodes))}

    def _popen(self, ctl, name, cmd):
        log = open(os.path.join(ctl.rt, f"{name}.log"), "w")
        self.procs.append(subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT))

    def start_server(self, ctl, node, cmd):
        port = ctl.ips[node["id"]].split(":")[1]
        self._popen(ctl, f"server_{node['id']}", cmd + ["--port", port])

    def start_agent(self, ctl, vid, cmd):
        self._popen(ctl, f"agent_{vid}", cmd)

    def stop(self, ctl):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()


class Controller:
    def __init__(self, sc: dict, seed: int, run_dir: str, meta: dict, adapter: BaseAdapter):
        self.sc = sc
        self.seed = seed
        self.run_dir = run_dir
        self.meta = meta
        self.adapter = adapter
        self.rt = os.path.join(run_dir, "_rt")
        if os.path.isdir(self.rt):
            shutil.rmtree(self.rt)
        os.makedirs(self.rt, exist_ok=True)
        self.pol = build_policies(sc)
        for p in self.pol.values():
            p.reset(seed)
        self.world = World(sc, seed, self.pol)
        self.ips: dict = {}

    # ------------------------------------------------------------------ état
    def node_pair_delays(self) -> dict:
        w = self.world
        out = {}
        for a, na in w.nodes.items():
            out[a] = {}
            for b, nb in w.nodes.items():
                out[a][b] = w.graph.path_delay_ms(na["site"], nb["site"])
        return out

    def publish(self, t: float, t0: float) -> None:
        w = self.world
        write_json_atomic(os.path.join(self.rt, "state.json"), {
            "t0": t0, "t": round(t, 4),
            "views": {vid: w.vehicle_view(vid) for vid in w.veh},
            "node_pair_delay_ms": self.node_pair_delays(),
        })
        for nid, n in w.nodes.items():
            write_json_atomic(os.path.join(self.rt, f"ctl_{nid}.json"), {"up": n["up"], "slowdown": n["slowdown"]})

    # ------------------------------------------------------------------ run
    def run(self, cli: bool = False) -> None:
        w = self.world
        sc = self.sc
        with open(os.path.join(self.rt, "scenario.json"), "w") as f:
            json.dump(sc, f)
        write_json_atomic(os.path.join(self.rt, "repo.json"), {"root": REPO_ROOT})
        self.ips = self.adapter.build(self)
        write_json_atomic(os.path.join(self.rt, "ips.json"), self.ips)

        w.step(0.0)
        self.adapter.apply(self, [])
        t0 = time.time() + 2.0          # instant zéro commun (dans le futur : laisse démarrer les serveurs)
        self.publish(0.0, t0)
        cv = str(sc["tasks"].get("jitter_cv", 0.1))
        rep = str(sc.get("load_report_s", 0.5))
        for nid, n in w.nodes.items():
            cmd = [sys.executable, "-m", "ubiq.apps.edge_server", "--rt", self.rt, "--node", nid,
                   "--workers", str(n["workers"]), "--service-ms", str(n["service_ms"]), "--cv", cv, "--report-s", rep]
            self.adapter.start_server(self, n, cmd)
        if cli:
            self.adapter.cli(self)
            self.adapter.stop(self)
            return

        for i, vid in enumerate(sorted(w.veh)):
            cmd = [sys.executable, "-m", "ubiq.apps.vehicle_agent", "--rt", self.rt, "--vid", vid,
                   "--seed", str(self.seed * 100 + i)]
            self.adapter.start_agent(self, vid, cmd)

        dur = w.duration
        k = 0
        late = 0
        while True:
            k += 1
            t_tick = k * w.dt
            if t_tick > dur + 3.0:
                break
            sleep = t0 + t_tick - time.time()
            if sleep > 0:
                time.sleep(sleep)
            else:
                late += 1
            if t_tick <= dur:
                changes = w.step(t_tick)
                self.adapter.apply(self, changes)
                self.publish(t_tick, t0)
        if late > 0.1 * k:
            print(f"[ubiq] ATTENTION : {late}/{k} ticks en retard -- machine trop chargée ?", flush=True)
        open(os.path.join(self.rt, "STOP"), "w").close()
        time.sleep(1.5)
        self.adapter.stop(self)
        self.merge()

    # ------------------------------------------------------------------ fusion des journaux
    def merge(self) -> None:
        w = self.world
        tasks, percs, events = [], [], list(w.event_rows)
        for vid in sorted(w.veh):
            tasks += metrics.read_csv(os.path.join(self.rt, f"agent_{vid}_tasks.csv"))
            percs += metrics.read_csv(os.path.join(self.rt, f"agent_{vid}_perc.csv"))
            events += metrics.read_csv(os.path.join(self.rt, f"agent_{vid}_events.csv"))
        receipts = []
        for f in glob.glob(os.path.join(self.rt, "receipts_*.csv")):
            with open(f, newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 4:
                        receipts.append({"vid": row[0], "t_gen": float(row[2]), "t_avail": float(row[3]),
                                         "accuracy": float(row[4]) if len(row) > 4 else 1.0})
        events.sort(key=lambda e: float(e["t"]))
        aoi_rows = []
        if (self.sc.get("perception") or {}).get("enabled"):
            aoi_rows, _ = metrics.aoi_samples(receipts, list(w.veh), w.duration, w.phase_of)
        rd = self.run_dir
        metrics.write_csv(f"{rd}/tasks.csv", tasks, metrics.TASK_FIELDS)
        metrics.write_csv(f"{rd}/perception.csv", percs, metrics.PERC_FIELDS)
        metrics.write_csv(f"{rd}/aoi.csv", aoi_rows, metrics.AOI_FIELDS)
        metrics.write_csv(f"{rd}/ticks.csv", w.tick_rows, metrics.TICK_FIELDS)
        metrics.write_csv(f"{rd}/events.csv", events, metrics.EVENT_FIELDS)
        metrics.write_csv(f"{rd}/uav.csv", w.uav_rows, metrics.UAV_FIELDS)
        meta = dict(self.meta)
        meta.update({"backend": type(self.adapter).__name__, "phases": w.phases, "vehicles": list(w.veh),
                     "ips": self.ips})
        metrics.dump_meta(rd, meta)


def run_local(sc, seed, run_dir, meta, cli=False):
    Controller(sc, seed, run_dir, meta, LocalAdapter()).run(cli=False)
