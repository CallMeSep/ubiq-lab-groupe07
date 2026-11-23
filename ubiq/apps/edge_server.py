"""Serveur de calcul (Edge, UAV-Edge ou Cloud) -- backend Mininet.

  python3 -m ubiq.apps.edge_server --rt <dossier> --node E1 --workers 2 --service-ms 20

- k workers, file FIFO : le calcul est ÉMULÉ par un sleep (reproductible
  sur n'importe quelle machine), mais l'attente dans la file est réelle.
- Publie périodiquement sa charge dans <rt>/load_<node>.json.
- Lit <rt>/ctl_<node>.json (écrit par le contrôleur) : up, slowdown.
- Les mises à jour de perception reçues sont journalisées (AoI).
"""
from __future__ import annotations

import argparse
import math
import os
import queue
import random
import socketserver
import threading
import time

from .proto import PORT, read_json, recv_line, recv_payload, send_msg, write_json_atomic


class Node:
    def __init__(self, a):
        self.a = a
        self.rt = a.rt
        self.q: queue.Queue = queue.Queue()
        self.in_system = 0
        self.lock = threading.Lock()
        self.rng = random.Random(hash(a.node) & 0xFFFF)
        self.ctl = {"up": True, "slowdown": 1.0}
        self.t0 = None
        self.receipts = open(os.path.join(self.rt, f"receipts_{a.node}.csv"), "a", buffering=1)
        for _ in range(a.workers):
            threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.reporter, daemon=True).start()

    def now(self) -> float:
        if self.t0 is None:
            st = read_json(os.path.join(self.rt, "state.json"), {})
            self.t0 = st.get("t0")
        return time.time() - (self.t0 or time.time())

    def jitter(self) -> float:
        cv = self.a.cv
        if cv <= 0:
            return 1.0
        s2 = math.log(1 + cv * cv)
        return self.rng.lognormvariate(-s2 / 2, math.sqrt(s2))

    def worker(self):
        while True:
            service_ms, done = self.q.get()
            time.sleep(service_ms * float(self.ctl.get("slowdown", 1.0)) * self.jitter() / 1000.0)
            done.set()

    def reporter(self):
        while True:
            c = read_json(os.path.join(self.rt, f"ctl_{self.a.node}.json"))
            if c:
                self.ctl = c
            if not self.ctl.get("up", True):     # en panne : plus de rapport (le dernier vieillit)
                time.sleep(self.a.report_s)
                continue
            write_json_atomic(os.path.join(self.rt, f"load_{self.a.node}.json"), {
                "queue": self.in_system, "workers": self.a.workers,
                "service_ms": self.a.service_ms * float(self.ctl.get("slowdown", 1.0)),
                "up": bool(self.ctl.get("up", True)), "t_report": round(self.now(), 4)})
            time.sleep(self.a.report_s)

    def process(self, service_ms: float) -> None:
        done = threading.Event()
        with self.lock:
            self.in_system += 1
        self.q.put((service_ms, done))
        done.wait()
        with self.lock:
            self.in_system -= 1


def make_handler(node: Node):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                while True:
                    if not node.ctl.get("up", True):   # nœud « en panne » : ne répond plus
                        return
                    h = recv_line(self.rfile)
                    if h is None:
                        return
                    recv_payload(self.rfile, int(h["size"]))
                    if h.get("kind") == "perc":
                        node.process(float(h.get("fusion_ms", 5)))
                        node.receipts.write(f"{h['vid']},{h['id']},{h['t_gen']},{node.now():.4f},{h.get('accuracy', 1.0)}\n")
                        send_msg(self.connection, {"ok": True}, 1)
                    else:
                        node.process(node.a.service_ms)
                        send_msg(self.connection, {"ok": True, "node": node.a.node}, int(float(h.get("out_kb", 1)) * 1000))
            except (ConnectionError, OSError, ValueError):
                return
    return Handler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rt", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--service-ms", type=float, default=20)
    ap.add_argument("--cv", type=float, default=0.1)
    ap.add_argument("--report-s", type=float, default=0.5)
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    node = Node(a)
    srv = Server(("0.0.0.0", a.port), make_handler(node))
    print(f"[edge_server] {a.node} prêt sur le port {a.port} ({a.workers} workers, {a.service_ms} ms)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
