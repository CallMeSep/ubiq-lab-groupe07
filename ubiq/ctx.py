"""Objets passés aux politiques. Identiques dans les deux backends.

Règle d'or : une politique ne voit QUE ce qu'un vrai système pourrait
observer. En particulier la charge des Edge est rapportée périodiquement
(champ `t_report`) : l'information de contrôle a elle-même un âge.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Task:
    id: str
    vid: str
    t_gen: float           # s
    input_kb: float
    output_kb: float
    deadline_ms: float


@dataclass
class EdgeLoad:
    queue: int             # tâches dans le système (attente + service)
    workers: int
    service_ms: float      # temps de service nominal par tâche
    up: bool               # vrai dès qu'un rapport arrive ; un nœud en panne cesse d'émettre
    t_report: float        # instant du dernier rapport (s) : regardez son âge !


@dataclass
class APView:
    id: str
    snr_db: float
    rate_mbps: float
    n_assoc: int
    is_uav: bool
    site: str


@dataclass
class VehicleCtx:
    t: float
    vid: str
    pos: tuple
    vel: tuple
    serving_ap: str | None
    serving_is_uav: bool
    snr_db: float
    uplink_mbps: float
    site: str | None                       # site du point d'accès courant
    nearest_edge: str | None               # Edge « le plus proche » (délai) du site courant
    candidates: list[str]                  # cibles valides : 'local', 'edge:E1', ..., 'cloud', 'service'
    path_delay_ms: dict[str, float]        # délai one-way (accès + filaire) vers chaque cible distante
    edge_load: dict[str, EdgeLoad]         # dernier rapport de charge par nœud de calcul
    aps_in_range: list[APView]
    local_queue: int                       # tâches en attente sur le CPU embarqué
    local_service_ms: float
    service_location: str | None = None    # pour les services avec état (variante B)
    service_available: bool = True
    history: dict[str, deque] = field(default_factory=dict)  # cible -> deque[(t, latence_ms, statut)]

    # --- aides -------------------------------------------------------------
    def last_latency_ms(self, target: str, default: float | None = None) -> float | None:
        h = self.history.get(target)
        if not h:
            return default
        for t, lat, st in reversed(h):
            if lat == lat:  # pas NaN
                return lat
        return default

    def mean_latency_ms(self, target: str, window_s: float = 5.0, default: float | None = None):
        h = self.history.get(target)
        if not h:
            return default
        vals = [lat for (t, lat, st) in h if self.t - t <= window_s and lat == lat]
        return sum(vals) / len(vals) if vals else default

    def load_age_s(self, node: str) -> float | None:
        ld = self.edge_load.get(node)
        return None if ld is None else self.t - ld.t_report


@dataclass
class UAVView:
    pos: tuple
    deployed: bool
    speed_mps: float
    climb_mps: float
    energy_j: float
    power_w: float


@dataclass
class NetView:
    """Vue réseau pour la politique UAV (côté opérateur, donc plus riche)."""
    t: float
    vehicles: dict[str, tuple]             # vid -> (x, y)
    serving: dict[str, str | None]         # vid -> AP courant
    aps: dict[str, dict]                   # id -> {pos, up, is_uav, site}
    ground_station: tuple                  # position de la station sol de l'UAV
    a2g_snr: Callable                      # a2g_snr(uav_pos, ue_pos) -> dB
    ground_snr: Callable                   # ground_snr(ap_id, ue_pos) -> dB
    backhaul_mbps: Callable                # backhaul_mbps(uav_pos) -> Mb/s
    snr_min_db: float
    zones: dict = field(default_factory=dict)  # zones d'intérêt (scénario), ex. pour la variante E
