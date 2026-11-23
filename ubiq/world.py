"""Le « monde » : positions, pannes, UAV, association, qualité des liens.

Ce module est COMMUN aux deux backends :
  - backend `sim`     : le monde alimente un simulateur à événements discrets ;
  - backend `mininet` : le monde est appliqué à Mininet-WiFi (association
    réelle via `iw`, débit/pertes via `tc`, pannes via `ip link`).
"""
from __future__ import annotations

import math
import random

from . import channel
from .ctx import APView, NetView, UAVView
from .energy import propulsion_power_w
from .mobility import TraceMobility, UAVKinematics
from .topology import SiteGraph

UAV_SITE = "UAVS"


def load_policy(spec: dict | None, default_cls: str):
    """spec = {'cls': 'module:Classe', 'args': {...}}"""
    import importlib
    spec = spec or {}
    path = spec.get("cls", default_cls)
    mod_name, cls_name = path.split(":")
    cls = getattr(importlib.import_module(mod_name), cls_name)
    return cls(**(spec.get("args") or {}))


def build_policies(sc: dict) -> dict:
    p = sc.get("policies", {})
    return {
        "offloading": load_policy(p.get("offloading"), "policies.baselines:AlwaysEdge"),
        "association": load_policy(p.get("association"), "policies.baselines:StrongestSNR"),
        "migration": load_policy(p.get("migration"), "policies.baselines:NoMigration"),
        "perception": load_policy(p.get("perception"), "policies.baselines:FixedPerception"),
        "uav": load_policy(p.get("uav"), "policies.baselines:HoverOver"),
    }


class World:
    def __init__(self, sc: dict, seed: int, policies: dict):
        self.sc = sc
        self.rng = random.Random(seed)
        self.dt = float(sc.get("tick_s", 0.1))
        self.duration = float(sc["duration_s"])
        radio = sc["radio"]
        self.ground = radio["ground"]
        self.a2g = radio["a2g"]
        self.ho_s = float(radio.get("handover_ms", 100)) / 1000.0
        self.access_ms = float(sc.get("access_delay_ms", 8))
        self.pol = policies

        self.graph = SiteGraph(sc["sites"], sc.get("wired", []))
        self.aps: dict[str, dict] = {}
        for a in sc["aps"]:
            self.aps[a["id"]] = {"id": a["id"], "pos": tuple(a["pos"]), "site": a["site"],
                                 "capacity": float(a.get("capacity_mbps", 25)), "up": True,
                                 "is_uav": False, "channel": a.get("channel", 1)}

        self.nodes: dict[str, dict] = {}
        for eid, e in (sc.get("edges") or {}).items():
            self.nodes[eid] = {"id": eid, "kind": "edge", "site": e["site"], "workers": int(e["workers"]),
                               "service_ms": float(e["service_ms"]), "up": True, "slowdown": 1.0}
        cl = sc.get("cloud")
        if cl:
            self.nodes["cloud"] = {"id": "cloud", "kind": "cloud", "site": cl["site"], "workers": int(cl["workers"]),
                                   "service_ms": float(cl["service_ms"]), "up": True, "slowdown": 1.0}

        # --- UAV ------------------------------------------------------------
        u = sc.get("uav") or {}
        self.uav_enabled = bool(u.get("enabled", False))
        self.uav = None
        if self.uav_enabled:
            self.uav_id = u.get("id", "UAV")
            gs = u["ground_station"]
            self.gs_pos = tuple(self.aps[gs]["pos"][:2]) + (float(u.get("gs_height", 10.0)),)
            self.gs_site = self.aps[gs]["site"]
            self.uav = UAVKinematics(u["depot"], float(u.get("speed_mps", 10)), float(u.get("climb_mps", 3)))
            self.uav_min_alt = float(u.get("min_alt", 10.0))
            self.uav_deployed = False
            self.uav_landing = False
            self.uav_energy_j = 0.0
            self.uav_power_w = 0.0
            self.uav_energy_params = u.get("energy") or {}
            self.bh_cfg = u.get("backhaul") or {}
            self.bh_rate = 0.0
            self.graph.sites.append(UAV_SITE)
            self.graph.links[frozenset((UAV_SITE, self.gs_site))] = {
                "a": UAV_SITE, "b": self.gs_site, "delay_ms": float(self.bh_cfg.get("delay_ms", 1.0)),
                "bw_mbps": 0.0, "up": False}
            self.aps[self.uav_id] = {"id": self.uav_id, "pos": tuple(self.uav.pos), "site": UAV_SITE,
                                     "capacity": float(u.get("capacity_mbps", 25)), "up": False,
                                     "is_uav": True, "channel": u.get("channel", 6)}
            if "edge" in str(u.get("role", "ap")):
                ue = u.get("edge") or {}
                self.nodes[self.uav_id] = {"id": self.uav_id, "kind": "edge", "site": UAV_SITE,
                                           "workers": int(ue.get("workers", 1)),
                                           "service_ms": float(ue.get("service_ms", 35)),
                                           "up": False, "slowdown": 1.0}

        # --- véhicules (mobilité subie) --------------------------------------
        vcfg = sc["vehicles"]
        self.trace = TraceMobility(vcfg["trace"])
        import re
        pool = [i for i in self.trace.ids if i.startswith(str(vcfg.get("id_prefix", "")))]
        pool.sort(key=lambda s: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)])
        ids = vcfg.get("ids") or pool[: int(vcfg.get("count", len(pool)))]
        self.veh: dict[str, dict] = {}
        for vid in ids:
            x, y = self.trace.position(vid, 0.0)
            self.veh[vid] = {"id": vid, "pos": (x, y, channel.GROUND_UE_HEIGHT), "vel": (0.0, 0.0),
                             "serving": None, "snr": -math.inf, "rate": 0.0, "epoch": 0,
                             "ho_until": 0.0, "n_ho": 0}

        self.events = sorted(sc.get("events") or [], key=lambda e: float(e["t"]))
        self._ev_i = 0
        self.phases = sc.get("phases") or [{"name": "all", "start": 0, "end": self.duration}]
        self.zones = sc.get("zones") or {}

        # journaux
        self.event_rows: list[dict] = []
        self.tick_rows: list[dict] = []
        self.uav_rows: list[dict] = []
        self.log_every = float(sc.get("log_every_s", 0.5))
        self._next_log = 0.0

    # ------------------------------------------------------------------ utils
    def phase_of(self, t: float) -> str:
        for p in self.phases:
            if p["start"] <= t < p["end"]:
                return p["name"]
        return self.phases[-1]["name"]

    def log_event(self, t: float, typ: str, target: str = "", detail: str = "") -> None:
        self.event_rows.append({"t": round(t, 4), "type": typ, "target": target, "detail": detail})

    def node_reachable_delay_ms(self, ap_id: str, node_id: str) -> float | None:
        """Délai one-way AP -> nœud de calcul (accès + filaire), None si injoignable.

        N'utilise que la TOPOLOGIE (liens actifs), jamais l'état « en panne » d'un
        nœud de calcul : un véhicule ne sait pas qu'un Edge est tombé, il le découvre
        (délais, échecs, rapports de charge qui n'arrivent plus)."""
        ap = self.aps.get(ap_id)
        node = self.nodes.get(node_id)
        if ap is None or node is None:
            return None
        d = self.graph.path_delay_ms(ap["site"], node["site"])
        if d is None:
            return None
        return self.access_ms + d

    def resolve_target(self, vid: str, target: str, service_loc: str | None = None) -> str | None:
        """Cible abstraite -> id de nœud (ou None si impossible)."""
        v = self.veh[vid]
        if target == "cloud":
            return "cloud" if "cloud" in self.nodes else None
        if target == "service":
            return service_loc
        if target.startswith("edge:"):
            name = target.split(":", 1)[1]
            if name != "nearest":
                return name if name in self.nodes else None
            if v["serving"] is None:
                return None
            best, best_d = None, math.inf
            for nid, n in sorted(self.nodes.items()):
                if n["kind"] != "edge":
                    continue
                d = self.node_reachable_delay_ms(v["serving"], nid)
                if d is not None and d < best_d:
                    best, best_d = nid, d
            return best
        return None

    def nearest_edge(self, vid: str) -> str | None:
        return self.resolve_target(vid, "edge:nearest")

    def aps_in_range(self, vid: str) -> list[APView]:
        v = self.veh[vid]
        n_assoc = {a: 0 for a in self.aps}
        for w in self.veh.values():
            if w["serving"]:
                n_assoc[w["serving"]] += 1
        out = []
        for a in self.aps.values():
            if not a["up"]:
                continue
            snr = self.link_snr(a, v["pos"])
            radio = self.a2g if a["is_uav"] else self.ground
            if snr >= radio.get("snr_min_db", 5.0):
                out.append(APView(a["id"], round(snr, 2), round(channel.rate_mbps(snr, radio), 2),
                                  n_assoc[a["id"]], a["is_uav"], a["site"]))
        return out

    def link_snr(self, ap: dict, ue_pos) -> float:
        if ap["is_uav"]:
            return channel.a2g_snr(ap["pos"], ue_pos, self.a2g)
        return channel.ground_snr(ap["pos"], ue_pos, self.ground)

    def uplink_rate(self, vid: str) -> float:
        v = self.veh[vid]
        if v["serving"] is None:
            return 0.0
        ap = self.aps[v["serving"]]
        return min(v["rate"], ap["capacity"])

    def backhaul_rate_at(self, pos) -> float:
        bh = self.bh_cfg
        radio = dict(self.a2g)
        radio["rate_max_mbps"] = bh.get("rate_max_mbps", 60)
        radio["bandwidth_mhz"] = bh.get("bandwidth_mhz", radio.get("bandwidth_mhz", 20))
        snr = channel.a2g_snr(tuple(pos), self.gs_pos, radio, gain_db=float(bh.get("gain_db", 10)),
                              ptx_dbm=float(bh.get("ptx_dbm", 23)))
        return channel.rate_mbps(snr, radio)

    def netview(self, t: float) -> NetView:
        return NetView(
            t=t,
            vehicles={vid: v["pos"][:2] for vid, v in self.veh.items()},
            serving={vid: v["serving"] for vid, v in self.veh.items()},
            aps={a["id"]: {"pos": a["pos"], "up": a["up"], "is_uav": a["is_uav"], "site": a["site"]}
                 for a in self.aps.values()},
            ground_station=self.gs_pos if self.uav_enabled else (0, 0, 0),
            a2g_snr=lambda up, ue: channel.a2g_snr(tuple(up), tuple(ue) if len(ue) > 2 else (ue[0], ue[1], channel.GROUND_UE_HEIGHT), self.a2g),
            ground_snr=lambda ap_id, ue: channel.ground_snr(self.aps[ap_id]["pos"], tuple(ue) if len(ue) > 2 else (ue[0], ue[1], channel.GROUND_UE_HEIGHT), self.ground),
            backhaul_mbps=self.backhaul_rate_at,
            snr_min_db=self.a2g.get("snr_min_db", 5.0),
            zones=self.zones,
        )

    # ------------------------------------------------------------------ events
    def _apply_event(self, t: float, ev: dict) -> None:
        typ = ev["type"]
        tgt = ev.get("target", "")
        if typ in ("ap_down", "ap_up"):
            self.aps[tgt]["up"] = typ == "ap_up"
        elif typ in ("edge_down", "edge_up"):
            self.nodes[tgt]["up"] = typ == "edge_up"
        elif typ == "edge_overload":
            self.nodes[tgt]["slowdown"] = float(ev.get("factor", 3.0))
        elif typ in ("link_down", "link_up"):
            self.graph.set_up(ev["a"], ev["b"], typ == "link_up")
            tgt = f"{ev['a']}-{ev['b']}"
        elif typ == "uav_launch" and self.uav_enabled:
            self.uav_deployed = True
            self.uav_landing = False
        elif typ == "uav_land" and self.uav_enabled:
            self.uav_landing = True
        else:
            raise ValueError(f"événement inconnu : {ev}")
        self.log_event(t, typ, tgt, str({k: v for k, v in ev.items() if k not in ('t', 'type', 'target')}))

    # ------------------------------------------------------------------ step
    def step(self, t: float) -> list[tuple[str, str | None, str | None]]:
        """Avance le monde à l'instant t. Renvoie la liste des handovers (vid, ancien, nouveau)."""
        while self._ev_i < len(self.events) and float(self.events[self._ev_i]["t"]) <= t + 1e-9:
            self._apply_event(t, self.events[self._ev_i])
            self._ev_i += 1

        for vid, v in self.veh.items():
            x, y = self.trace.position(vid, t)
            v["pos"] = (x, y, channel.GROUND_UE_HEIGHT)
            v["vel"] = self.trace.velocity(vid, t)

        if self.uav_enabled:
            self._step_uav(t)

        changes = []
        for vid in sorted(self.veh):
            v = self.veh[vid]
            cands = self.aps_in_range(vid)
            cur = v["serving"] if v["serving"] in {c.id for c in cands} else None
            choice = self.pol["association"].choose(vid, t, cur, cands)
            if choice is not None and choice not in {c.id for c in cands}:
                choice = None
            if choice != v["serving"]:
                old = v["serving"]
                v["serving"] = choice
                v["epoch"] += 1
                if choice is not None:
                    v["ho_until"] = t + self.ho_s
                    v["n_ho"] += 1
                self.log_event(t, "handover" if (old and choice) else ("attach" if choice else "detach"),
                               vid, f"{old}->{choice}")
                changes.append((vid, old, choice))
            if v["serving"]:
                a = self.aps[v["serving"]]
                v["snr"] = self.link_snr(a, v["pos"])
                v["rate"] = channel.rate_mbps(v["snr"], self.a2g if a["is_uav"] else self.ground)
            else:
                v["snr"], v["rate"] = -math.inf, 0.0

        if t + 1e-9 >= self._next_log:
            self._next_log += self.log_every
            for vid, v in self.veh.items():
                self.tick_rows.append({"t": round(t, 3), "vid": vid, "x": round(v["pos"][0], 2),
                                       "y": round(v["pos"][1], 2), "serving": v["serving"] or "",
                                       "snr_db": round(v["snr"], 2) if v["snr"] > -1e9 else "",
                                       "rate_mbps": round(v["rate"], 2)})
            if self.uav_enabled:
                self.uav_rows.append({"t": round(t, 3), "x": round(self.uav.pos[0], 2),
                                      "y": round(self.uav.pos[1], 2), "h": round(self.uav.pos[2], 2),
                                      "v_h": round(self.uav.v_h, 2), "power_w": round(self.uav_power_w, 1),
                                      "energy_j": round(self.uav_energy_j, 1),
                                      "ap_up": int(self.aps[self.uav_id]["up"]),
                                      "backhaul_mbps": round(self.bh_rate, 2),
                                      "n_served": sum(1 for w in self.veh.values() if w["serving"] == self.uav_id)})
        return changes

    def _step_uav(self, t: float) -> None:
        u = self.uav
        if self.uav_deployed:
            if self.uav_landing:
                depot = self.sc["uav"]["depot"]
                target = (depot[0], depot[1], 0.0)
            else:
                view = UAVView(tuple(u.pos), True, u.speed, u.climb, self.uav_energy_j, self.uav_power_w)
                target = self.pol["uav"].waypoint(t, view, self.netview(t))
                target = (float(target[0]), float(target[1]), max(0.0, float(target[2])))
            u.step(target, self.dt)
            self.uav_power_w = propulsion_power_w(u.v_h, u.v_z, self.uav_energy_params) if u.pos[2] > 0.5 else 0.0
            self.uav_energy_j += self.uav_power_w * self.dt
            if self.uav_landing and u.pos[2] <= 0.5:
                self.uav_deployed = False
        else:
            self.uav_power_w = 0.0
        airborne = self.uav_deployed and u.pos[2] >= self.uav_min_alt
        self.bh_rate = self.backhaul_rate_at(u.pos) if airborne else 0.0
        up = airborne and self.bh_rate > 0
        ap = self.aps[self.uav_id]
        ap["pos"] = tuple(u.pos)
        if ap["up"] != up:
            self.log_event(t, "uav_ap_up" if up else "uav_ap_down", self.uav_id, f"pos={tuple(round(p,1) for p in u.pos)}")
        ap["up"] = up
        self.graph.links[frozenset((UAV_SITE, self.gs_site))]["up"] = up
        self.graph.links[frozenset((UAV_SITE, self.gs_site))]["bw_mbps"] = self.bh_rate
        if self.uav_id in self.nodes:
            self.nodes[self.uav_id]["up"] = up

    # ------------------------------------------------------------------ vues
    def remote_targets(self) -> list[str]:
        t = ["edge:nearest"] + [f"edge:{nid}" for nid, n in sorted(self.nodes.items()) if n["kind"] == "edge"]
        if "cloud" in self.nodes:
            t.append("cloud")
        if (self.sc.get("service") or {}).get("stateful", False):
            t.append("service")
        return t

    def vehicle_view(self, vid: str, service_loc: str | None = None) -> dict:
        """Vue sérialisable (JSON) d'un véhicule : publiée par le contrôleur
        Mininet dans state.json, utilisée directement par le simulateur."""
        v = self.veh[vid]
        serving = v["serving"]
        ap = self.aps.get(serving) if serving else None
        delays = {}
        cands = ["local"]
        if serving:
            for tg in self.remote_targets():
                node = self.resolve_target(vid, tg, service_loc)
                d = self.node_reachable_delay_ms(serving, node) if node else None
                delays[tg] = d if d is not None else float("inf")
                cands.append(tg)
        return {
            "vid": vid, "pos": list(v["pos"]), "vel": list(v["vel"]),
            "serving": serving, "serving_is_uav": bool(ap and ap["is_uav"]),
            "snr_db": v["snr"] if v["snr"] > -1e9 else -999.0,
            "uplink_mbps": self.uplink_rate(vid),
            "site": ap["site"] if ap else None,
            "nearest_edge": self.nearest_edge(vid),
            "candidates": cands, "path_delay_ms": delays,
            "node_delay_ms": {nid: (self.node_reachable_delay_ms(serving, nid) if serving else None)
                              for nid in self.nodes},
            "aps_in_range": [a.__dict__ for a in self.aps_in_range(vid)],
            "epoch": v["epoch"], "ho_until": v["ho_until"],
        }
