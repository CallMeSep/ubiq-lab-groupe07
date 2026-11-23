"""Construction du VehicleCtx à partir d'une vue du monde + état local du véhicule."""
from __future__ import annotations

from .ctx import APView, EdgeLoad, VehicleCtx


def make_ctx(view: dict, t: float, edge_load: dict, local_queue: int, local_service_ms: float,
             service_location: str | None, service_available: bool, history: dict) -> VehicleCtx:
    loads = {}
    for nid, ld in (edge_load or {}).items():
        loads[nid] = ld if isinstance(ld, EdgeLoad) else EdgeLoad(**ld)
    return VehicleCtx(
        t=t, vid=view["vid"], pos=tuple(view["pos"]), vel=tuple(view["vel"]),
        serving_ap=view["serving"], serving_is_uav=view["serving_is_uav"],
        snr_db=view["snr_db"], uplink_mbps=view["uplink_mbps"], site=view["site"],
        nearest_edge=view["nearest_edge"], candidates=list(view["candidates"]),
        path_delay_ms=dict(view["path_delay_ms"]), edge_load=loads,
        aps_in_range=[APView(**a) for a in view["aps_in_range"]],
        local_queue=local_queue, local_service_ms=local_service_ms,
        service_location=service_location, service_available=service_available,
        history=history,
    )
