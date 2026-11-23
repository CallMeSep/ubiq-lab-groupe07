"""Modèles de canal volontairement simples (et assumés comme tels).

- Sol  : perte log-distance  PL(d) = PL(1 m) + 10 n log10(d)
- A2G  : Al-Hourani et al., IEEE WCL 2014 :
         PL = FSPL(d) + P_LoS * eta_LoS + (1 - P_LoS) * eta_NLoS
         P_LoS = 1 / (1 + a exp(-b (theta - a))),  theta en degrés
- Débit : Shannon pondéré par une efficacité, plafonné.

Ces modèles servent à décider QUI peut s'associer à QUEL point d'accès
et avec QUEL débit. Ils ne prétendent pas représenter un vrai canal.
"""
from __future__ import annotations

import math

C = 3e8
GROUND_UE_HEIGHT = 1.5  # m

# (a, b, eta_LoS dB, eta_NLoS dB) -- Al-Hourani 2014, table I
AL_HOURANI = {
    "suburban": (4.88, 0.43, 0.1, 21.0),
    "urban": (9.61, 0.16, 1.0, 20.0),
    "dense_urban": (12.08, 0.11, 1.6, 23.0),
    "highrise": (27.23, 0.08, 2.3, 34.0),
}


def dist2d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def dist3d(a, b) -> float:
    za = a[2] if len(a) > 2 else 0.0
    zb = b[2] if len(b) > 2 else 0.0
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (za - zb) ** 2)


def ground_pathloss_db(d: float, pl1m_db: float, exponent: float) -> float:
    return pl1m_db + 10.0 * exponent * math.log10(max(d, 1.0))


def fspl_db(d: float, freq_ghz: float) -> float:
    d = max(d, 1.0)
    return 20 * math.log10(d) + 20 * math.log10(freq_ghz * 1e9) + 20 * math.log10(4 * math.pi / C)


def p_los(elev_deg: float, env: str = "urban") -> float:
    a, b, _, _ = AL_HOURANI[env]
    return 1.0 / (1.0 + a * math.exp(-b * (elev_deg - a)))


def a2g_pathloss_db(uav_pos, gnd_pos, freq_ghz: float = 2.4, env: str = "urban") -> float:
    _, _, eta_los, eta_nlos = AL_HOURANI[env]
    zu = uav_pos[2]
    zg = gnd_pos[2] if len(gnd_pos) > 2 else GROUND_UE_HEIGHT
    h = max(zu - zg, 0.1)
    r = dist2d(uav_pos, gnd_pos)
    elev = math.degrees(math.atan2(h, r))
    p = p_los(elev, env)
    return fspl_db(dist3d(uav_pos, gnd_pos), freq_ghz) + p * eta_los + (1 - p) * eta_nlos


def snr_db(ptx_dbm: float, pl_db: float, noise_dbm: float, gain_db: float = 0.0) -> float:
    return ptx_dbm + gain_db - pl_db - noise_dbm


def rate_mbps(snr: float, radio: dict) -> float:
    """Débit utile (Mb/s) ; 0 si SNR < seuil."""
    if snr < radio.get("snr_min_db", 5.0):
        return 0.0
    bw = radio.get("bandwidth_mhz", 20.0)
    eff = radio.get("efficiency", 0.3)
    rmax = radio.get("rate_max_mbps", 30.0)
    return min(rmax, bw * math.log2(1 + 10 ** (snr / 10)) * eff)


def ground_snr(ap_pos, ue_pos, radio: dict) -> float:
    pl = ground_pathloss_db(dist3d(ap_pos, ue_pos), radio["pl1m_db"], radio["exponent"])
    return snr_db(radio["ptx_dbm"], pl, radio["noise_dbm"])


def a2g_snr(uav_pos, ue_pos, radio: dict, gain_db: float = 0.0, ptx_dbm: float | None = None) -> float:
    pl = a2g_pathloss_db(uav_pos, ue_pos, radio.get("freq_ghz", 2.4), radio.get("env", "urban"))
    p = radio["ptx_dbm"] if ptx_dbm is None else ptx_dbm
    return snr_db(p, pl, radio["noise_dbm"], gain_db)


def a2g_coverage_radius(h: float, radio: dict, r_max: float = 3000.0, step: float = 1.0) -> float:
    """Rayon horizontal (m) sur lequel SNR >= seuil, pour un UAV à l'altitude h."""
    best = 0.0
    r = 0.0
    while r <= r_max:
        if a2g_snr((0.0, 0.0, h), (r, 0.0, GROUND_UE_HEIGHT), radio) >= radio.get("snr_min_db", 5.0):
            best = r
        r += step
    return best


def optimal_altitude(radio: dict, h_min: float = 10, h_max: float = 500, step: float = 5) -> tuple[float, float]:
    """(h*, R(h*)) par balayage."""
    best_h, best_r = h_min, -1.0
    h = h_min
    while h <= h_max:
        r = a2g_coverage_radius(h, radio, step=2.0)
        if r > best_r:
            best_h, best_r = h, r
        h += step
    return best_h, best_r
