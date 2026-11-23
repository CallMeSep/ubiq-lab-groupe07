"""Backend `mininet` : les applications tournent dans Mininet-WiFi.

Ce que Mininet-WiFi apporte ici : de vraies piles réseau (TCP/IP, ARP,
apprentissage MAC des commutateurs), de vraies associations 802.11 (`iw`)
avec leur temps de handover, de vraies files d'attente (tc/htb) sur les
liens filaires, et de vrais processus applicatifs.

Ce qu'il n'apporte PAS : un canal radio réaliste. La qualité des liens est
donc imposée par le modèle du monde (ubiq/channel.py) :
  - quel AP sert quel véhicule   -> décidé par la politique d'association,
                                    appliqué par `iw dev ... connect` ;
  - débit montant du véhicule    -> `tc netem rate` sur l'interface wlan ;
  - capacité partagée d'un AP    -> lien AP <-> commutateur (TCLink bw) ;
  - backhaul de l'UAV            -> TCLink reconfiguré à chaud.

Topologie : un commutateur OVS (mode standalone = apprentissage L2) par
site ; les sites forment un ARBRE (pas de boucle L2).

!!! Points à valider lors de la mise en place (voir docs/ENSEIGNANT.md) :
    OVSKernelAP en failMode=standalone, `iw connect` manuel, TCIntf.config
    à chaud, ip link down/up d'un AP.
"""
from __future__ import annotations

import os
import subprocess

from ..config import REPO_ROOT
from ..world import UAV_SITE
from .controller import BaseAdapter, Controller


class MininetAdapter(BaseAdapter):
    def __init__(self):
        self.net = None
        self.names: dict[str, str] = {}      # id du monde -> nom Mininet
        self.site_sw: dict[str, object] = {}
        self.ap_nodes: dict[str, object] = {}
        self.sta: dict[str, object] = {}
        self.hosts: dict[str, object] = {}
        self.bh_link = None
        self.shaped: dict[str, float] = {}
        self.assoc: dict[str, str | None] = {}
        self.ap_state: dict[str, bool] = {}
        self.node_state: dict[str, bool] = {}
        self.link_state: dict = {}
        self.bh_rate_applied = -1.0
        self.procs = []

    # ------------------------------------------------------------------ build
    def build(self, ctl: Controller) -> dict:
        from mininet.link import TCLink
        from mininet.log import setLogLevel
        from mininet.node import OVSKernelSwitch
        from mn_wifi.net import Mininet_wifi
        from mn_wifi.node import OVSKernelAP

        setLogLevel(os.environ.get("UBIQ_MN_LOG", "warning"))
        subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        w = ctl.world
        sc = ctl.sc
        mcfg = sc.get("mininet") or {}
        prefix = mcfg.get("ip_prefix", "10.0.0.")
        mode = mcfg.get("wifi_mode", "g")
        net = Mininet_wifi(accessPoint=OVSKernelAP, switch=OVSKernelSwitch, controller=None)
        self.net = net

        # sites -> commutateurs
        for i, site in enumerate(w.graph.sites, 1):
            self.site_sw[site] = net.addSwitch(f"s{i}", failMode="standalone")
        for ln in w.graph.tree_edges():
            a, b = self.site_sw[ln["a"]], self.site_sw[ln["b"]]
            bw = ln["bw_mbps"] if ln["bw_mbps"] > 0 else 10
            link = net.addLink(a, b, cls=TCLink, delay=f"{ln['delay_ms']}ms", bw=min(bw, 1000))
            key = frozenset((ln["a"], ln["b"]))
            if UAV_SITE in key:
                self.bh_link = link
            self.link_state[key] = True

        ips = {}
        # nœuds de calcul
        for k, (nid, n) in enumerate(sorted(w.nodes.items()), 11):
            name = "cloud" if nid == "cloud" else f"e{k}"
            ip = f"{prefix}{100 if nid == 'cloud' else k}"
            h = net.addHost(name, ip=f"{ip}/8")
            net.addLink(h, self.site_sw[n["site"]])
            self.hosts[nid] = h
            self.names[nid] = name
            ips[nid] = ip
            self.node_state[nid] = True

        # points d'accès (sol + UAV) : délai d'accès one-way + capacité partagée
        for k, (aid, a) in enumerate(w.aps.items(), 1):
            name = f"ap{k if not a['is_uav'] else 9}"
            pos = ",".join(str(round(v, 1)) for v in a["pos"])
            ap = net.addAccessPoint(name, ssid=f"ubiq-{aid}", mode=mode, channel=str(a.get("channel", 1)),
                                    position=pos, range=1000, failMode="standalone")
            self.ap_nodes[aid] = ap
            self.names[aid] = name
            net.addLink(ap, self.site_sw[a["site"]], cls=TCLink, delay=f"{w.access_ms}ms",
                        bw=min(a["capacity"], 1000))
            self.ap_state[aid] = True

        # véhicules
        for k, vid in enumerate(sorted(w.veh), 1):
            x, y, z = w.veh[vid]["pos"]
            self.sta[vid] = net.addStation(f"sta{k}", ip=f"10.0.1.{k}/8", position=f"{x:.1f},{y:.1f},0")
            self.names[vid] = f"sta{k}"
            self.assoc[vid] = None

        configure = getattr(net, "configureNodes", None) or getattr(net, "configureWifiNodes")
        configure()
        net.build()
        net.start()
        self.edge_ip = next(iter(ips.values()))
        return ips

    # ------------------------------------------------------------------ applis
    def _popen(self, node, name, ctl, cmd):
        log = open(os.path.join(ctl.rt, f"{name}.log"), "w")
        self.procs.append(node.popen(cmd, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT))

    def start_server(self, ctl, node, cmd):
        self._popen(self.hosts[node["id"]], f"server_{node['id']}", ctl, cmd)

    def start_agent(self, ctl, vid, cmd):
        self._popen(self.sta[vid], f"agent_{vid}", ctl, cmd)

    # ------------------------------------------------------------------ application de l'état du monde
    def apply(self, ctl, changes):
        w = ctl.world
        mcfg = ctl.sc.get("mininet") or {}
        # 1. pannes / remises en service des AP
        for aid, a in w.aps.items():
            if self.ap_state.get(aid) != a["up"]:
                ap = self.ap_nodes[aid]
                ap.cmd(f"ip link set {ap.name}-wlan1 {'up' if a['up'] else 'down'}")
                self.ap_state[aid] = a["up"]
        # 2. nœuds de calcul
        for nid, n in w.nodes.items():
            if self.node_state.get(nid) != n["up"]:
                h = self.hosts[nid]
                h.cmd(f"ip link set {h.name}-eth0 {'up' if n['up'] else 'down'}")
                self.node_state[nid] = n["up"]
        # 3. liens filaires coupés
        for key, ln in w.graph.links.items():
            if UAV_SITE in key:
                continue
            if self.link_state.get(key) != ln["up"]:
                self.net.configLinkStatus(self.site_sw[ln["a"]].name, self.site_sw[ln["b"]].name,
                                          "up" if ln["up"] else "down")
                self.link_state[key] = ln["up"]
        # 4. backhaul UAV (débit fonction de la position)
        if w.uav_enabled and self.bh_link is not None:
            r = max(w.bh_rate, 0.1)
            if self.bh_rate_applied < 0 or abs(r - self.bh_rate_applied) / max(self.bh_rate_applied, 0.1) > 0.15:
                for intf in (self.bh_link.intf1, self.bh_link.intf2):
                    intf.config(bw=min(r, 1000), delay="1ms")
                self.bh_rate_applied = r
        # 5. association (décidée par la politique, appliquée par iw) + débit montant (tc)
        thr = float(mcfg.get("shaping_min_change", 0.15))
        for vid, v in w.veh.items():
            sta = self.sta[vid]
            intf = f"{sta.name}-wlan0"
            if v["serving"] != self.assoc[vid]:
                sta.cmd(f"iw dev {intf} disconnect")
                if v["serving"]:
                    sta.cmd(f"iw dev {intf} connect ubiq-{v['serving']}")
                    sta.cmd(f"(sleep 0.3; ping -c1 -W1 {self.edge_ip} >/dev/null 2>&1) &")
                self.assoc[vid] = v["serving"]
            rate = max(w.uplink_rate(vid), 0.1)
            old = self.shaped.get(vid)
            if old is None or abs(rate - old) / old > thr:
                sta.cmd(f"tc qdisc replace dev {intf} root netem rate {rate:.2f}mbit")
                self.shaped[vid] = rate
            if mcfg.get("update_positions"):
                try:
                    sta.setPosition(f"{v['pos'][0]:.1f},{v['pos'][1]:.1f},0")
                except Exception:
                    pass
        if mcfg.get("update_positions") and w.uav_enabled:
            try:
                p = w.uav.pos
                self.ap_nodes[w.uav_id].setPosition(f"{p[0]:.1f},{p[1]:.1f},{p[2]:.1f}")
            except Exception:
                pass

    def cli(self, ctl):
        from mn_wifi.cli import CLI
        print("[ubiq] CLI Mininet-WiFi. Nœuds :", ", ".join(f"{k}={v}" for k, v in self.names.items()))
        CLI(self.net)

    def stop(self, ctl):
        for p in self.procs:
            try:
                p.terminate()
            except Exception:
                pass
        try:
            self.net.stop()
        finally:
            subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_mininet(sc, seed, run_dir, meta, cli=False):
    Controller(sc, seed, run_dir, meta, MininetAdapter()).run(cli=cli)
