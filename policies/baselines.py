"""Politiques de référence (baselines) fournies. NE PAS MODIFIER :
copiez-les dans votre fichier de groupe si vous voulez partir de là."""
from __future__ import annotations

from policies.base import (AssociationPolicy, MigrationPolicy, OffloadingPolicy,
                           PerceptionPolicy, UAVPolicy)


# ---------------------------------------------------------------- offloading
class AlwaysLocal(OffloadingPolicy):
    def decide(self, task, ctx):
        return "local"


class AlwaysEdge(OffloadingPolicy):
    """Edge le plus proche du point d'accès courant ; local si pas de couverture."""
    def decide(self, task, ctx):
        return "edge:nearest" if ctx.serving_ap else "local"


class AlwaysCloud(OffloadingPolicy):
    def decide(self, task, ctx):
        return "cloud" if ctx.serving_ap else "local"


class AlwaysService(OffloadingPolicy):
    """Service avec état (variante B) : toujours vers l'instance du véhicule."""
    def decide(self, task, ctx):
        return "service" if ctx.serving_ap else "local"


# ---------------------------------------------------------------- association
class StrongestSNR(AssociationPolicy):
    """SNR le plus fort, avec hystérésis pour éviter le ping-pong."""
    def __init__(self, hysteresis_db: float = 3.0, **kw):
        super().__init__(hysteresis_db=hysteresis_db, **kw)
        self.h = hysteresis_db

    def choose(self, vid, t, current, candidates):
        if not candidates:
            return None
        best = max(candidates, key=lambda a: a.snr_db)
        cur = next((a for a in candidates if a.id == current), None)
        if cur is not None and best.snr_db < cur.snr_db + self.h:
            return cur.id
        return best.id


# ---------------------------------------------------------------- migration
class NoMigration(MigrationPolicy):
    def decide(self, ctx):
        return None


class FollowMe(MigrationPolicy):
    """Migre dès que l'Edge le plus proche n'est plus celui du service."""
    def decide(self, ctx):
        if ctx.nearest_edge and ctx.service_location and ctx.nearest_edge != ctx.service_location:
            return ctx.nearest_edge
        return None


# ---------------------------------------------------------------- perception
class FixedPerception(PerceptionPolicy):
    def __init__(self, repr: str = "objects", rate_hz: float = 2.0, **kw):
        super().__init__(repr=repr, rate_hz=rate_hz, **kw)
        self.r, self.f = repr, rate_hz

    def choose(self, t, ctx):
        return self.r, self.f


# ---------------------------------------------------------------- UAV
class StayAtDepot(UAVPolicy):
    """Pas d'UAV (référence « sans drone »)."""
    def waypoint(self, t, uav, net):
        return (uav.pos[0], uav.pos[1], 0.0)


class HoverOver(UAVPolicy):
    """Se place au-dessus d'un point fixe (par défaut : l'AP en panne)."""
    def __init__(self, x: float = 300.0, y: float = 20.0, h: float = 60.0, **kw):
        super().__init__(x=x, y=y, h=h, **kw)
        self.target = (x, y, h)

    def waypoint(self, t, uav, net):
        return self.target
