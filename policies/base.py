"""Interfaces des politiques (NE PAS MODIFIER).

Vous écrivez vos politiques dans policies/group_XX.py en héritant de ces
classes, puis vous les référencez dans votre fichier d'expérience :

    policies.offloading.cls: policies.group_07:MyOffloading
    policies.offloading.args: {seuil_ms: 120}

Qui décide quoi, à quelle échelle de temps ?
  - AssociationPolicy : réseau,    à chaque tick (~100 ms)
  - OffloadingPolicy  : véhicule,  à chaque tâche (~100-200 ms)
  - PerceptionPolicy  : véhicule,  à chaque mise à jour de perception
  - MigrationPolicy   : véhicule/orchestrateur, à chaque tick
  - UAVPolicy         : opérateur, à chaque tick (mobilité PILOTÉE)
"""
from __future__ import annotations

from ubiq.ctx import APView, NetView, Task, UAVView, VehicleCtx


class Policy:
    def __init__(self, **kwargs):
        self.params = kwargs

    def reset(self, seed: int = 0) -> None:
        """Appelé au début de chaque run (réinitialiser l'état interne)."""


class OffloadingPolicy(Policy):
    def decide(self, task: Task, ctx: VehicleCtx) -> str:
        """Renvoie une cible de ctx.candidates :
        'local' | 'edge:nearest' | 'edge:<id>' | 'cloud' | 'service'."""
        raise NotImplementedError


class AssociationPolicy(Policy):
    def choose(self, vid: str, t: float, current: str | None, candidates: list[APView]) -> str | None:
        """Renvoie l'id de l'AP choisi (ou None). `candidates` = AP à portée."""
        raise NotImplementedError


class MigrationPolicy(Policy):
    def decide(self, ctx: VehicleCtx) -> str | None:
        """Renvoie l'id d'un Edge vers lequel migrer le service, ou None."""
        return None


class PerceptionPolicy(Policy):
    def choose(self, t: float, ctx: VehicleCtx) -> tuple[str, float]:
        """Renvoie (représentation, fréquence en Hz) pour la prochaine mise à jour.
        Représentations : 'raw' | 'features' | 'objects'."""
        raise NotImplementedError


class UAVPolicy(Policy):
    def waypoint(self, t: float, uav: UAVView, net: NetView) -> tuple[float, float, float]:
        """Renvoie le point de passage (x, y, h) visé."""
        raise NotImplementedError
