"""Petits outils autorisés dans vos politiques (aucune politique toute faite ici)."""
from __future__ import annotations

import math


def tx_time_ms(size_kb: float, rate_mbps: float) -> float:
    """Temps d'émission (ms) d'un message de size_kb kilo-octets à rate_mbps Mb/s."""
    return math.inf if rate_mbps <= 0 else size_kb * 8.0 / rate_mbps


def mmk_wait_ms(queue: int, workers: int, service_ms: float) -> float:
    """Estimation grossière de l'attente dans une file à `workers` serveurs
    contenant déjà `queue` tâches (attente + service)."""
    return max(0, queue - workers + 1) * service_ms / max(workers, 1)


def covered_vehicles(net, uav_pos) -> list[str]:
    """Véhicules qu'un UAV placé en uav_pos=(x, y, h) couvrirait (SNR >= seuil)."""
    return [vid for vid, (x, y) in net.vehicles.items() if net.a2g_snr(uav_pos, (x, y)) >= net.snr_min_db]


def uncovered_by_ground(net) -> list[str]:
    """Véhicules qu'aucun AP au sol en service ne couvre."""
    out = []
    for vid, (x, y) in net.vehicles.items():
        ok = any(net.ground_snr(aid, (x, y)) >= net.snr_min_db
                 for aid, a in net.aps.items() if a["up"] and not a["is_uav"])
        if not ok:
            out.append(vid)
    return out
