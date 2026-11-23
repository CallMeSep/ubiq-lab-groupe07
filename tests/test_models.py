"""Tests unitaires des modèles (sans Mininet). `python3 tests/test_models.py` ou `pytest`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ubiq import channel, energy  # noqa: E402
from ubiq.config import load_experiment  # noqa: E402
from ubiq.topology import SiteGraph  # noqa: E402

A2G = {"env": "urban", "freq_ghz": 2.4, "ptx_dbm": 0, "noise_dbm": -90, "snr_min_db": 5,
       "bandwidth_mhz": 20, "efficiency": 0.3, "rate_max_mbps": 30}
GROUND = {"ptx_dbm": 20, "pl1m_db": 40, "exponent": 3.0, "noise_dbm": -90, "snr_min_db": 5,
          "bandwidth_mhz": 20, "efficiency": 0.3, "rate_max_mbps": 30}


def test_altitude_optimum_exists():
    r30 = channel.a2g_coverage_radius(30, A2G)
    h_star, r_star = channel.optimal_altitude(A2G)
    r_high = channel.a2g_coverage_radius(h_star * 2, A2G)
    assert r_star > r30 and r_star > r_high, (r30, r_star, r_high)
    assert 40 <= h_star <= 200


def test_ground_range():
    assert channel.rate_mbps(channel.ground_snr((0, 0, 6), (100, 0, 1.5), GROUND), GROUND) > 0
    assert channel.rate_mbps(channel.ground_snr((0, 0, 6), (200, 0, 1.5), GROUND), GROUND) == 0


def test_hover_power():
    p0 = energy.hover_power_w()
    assert 160 < p0 < 175, p0                     # ~168 W (Zeng et al. 2019)
    # la puissance passe par un minimum à vitesse modérée, puis remonte
    p10, p30 = energy.propulsion_power_w(10), energy.propulsion_power_w(30)
    assert p10 < p0 < p30


def test_graph():
    g = SiteGraph({"A": {}, "B": {}, "C": {}}, [{"a": "A", "b": "B", "delay_ms": 5}, {"a": "B", "b": "C", "delay_ms": 7}])
    assert g.path_delay_ms("A", "C") == 12
    g.set_up("A", "B", False)
    assert g.path_delay_ms("A", "C") is None


def test_experiments_load():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in os.listdir(os.path.join(here, "experiments")):
        if f.endswith(".yaml"):
            load_experiment(os.path.join("experiments", f))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")
