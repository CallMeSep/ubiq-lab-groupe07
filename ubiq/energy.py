"""Puissance de propulsion d'un multirotor.

Y. Zeng, J. Xu, R. Zhang, "Energy Minimization for Wireless Communication
With Rotary-Wing UAV", IEEE TWC 18(4), 2019, éq. (12) et table I.

    P(V) = P0 (1 + 3V^2/U_tip^2)
         + Pi sqrt( sqrt(1 + V^4/(4 v0^4)) - V^2/(2 v0^2) )
         + 1/2 d0 rho s A V^3

On ajoute un terme de montée simple  W * max(vz, 0)  (W = poids en N).
"""
from __future__ import annotations

import math

ZENG_DEFAULT = {
    "P0": 79.86,     # W, puissance de profil de pale (vol stationnaire)
    "Pi": 88.63,     # W, puissance induite (vol stationnaire)
    "U_tip": 120.0,  # m/s
    "v0": 4.03,      # m/s, vitesse induite moyenne en stationnaire
    "d0": 0.6,       # rapport de traînée du fuselage
    "rho": 1.225,    # kg/m3
    "s": 0.05,       # solidité du rotor
    "A": 0.503,      # m2, surface du disque rotor
    "W": 20.0,       # N, poids
}


def propulsion_power_w(v_h: float, v_z: float = 0.0, p: dict | None = None) -> float:
    q = dict(ZENG_DEFAULT)
    if p:
        q.update(p)
    V = abs(v_h)
    blade = q["P0"] * (1 + 3 * V ** 2 / q["U_tip"] ** 2)
    induced = q["Pi"] * math.sqrt(max(math.sqrt(1 + V ** 4 / (4 * q["v0"] ** 4)) - V ** 2 / (2 * q["v0"] ** 2), 0.0))
    parasite = 0.5 * q["d0"] * q["rho"] * q["s"] * q["A"] * V ** 3
    climb = q["W"] * max(v_z, 0.0)
    return blade + induced + parasite + climb


def hover_power_w(p: dict | None = None) -> float:
    return propulsion_power_w(0.0, 0.0, p)
