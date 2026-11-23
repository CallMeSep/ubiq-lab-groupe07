"""Politiques du groupe XX -- copiez ce fichier en policies/group_<numéro>.py.

Règles :
  1. Vous ne modifiez QUE vos fichiers policies/group_<n>.py et experiments/group_<n>.yaml.
     Le code de ubiq/ est commun à toute la promotion et ne doit pas être modifié.
  2. Une politique ne doit utiliser QUE ce qu'elle reçoit (ctx, net, ...) : pas de lecture
     de fichiers internes, pas d'oracle.
  3. Chaque paramètre de vos politiques passe par __init__ (et donc par le YAML), pour
     pouvoir être balayé.

Voir policies/base.py pour les interfaces et policies/baselines.py pour des exemples.
"""
from policies.base import (AssociationPolicy, MigrationPolicy, OffloadingPolicy,
                           PerceptionPolicy, UAVPolicy)
from policies import helpers  # noqa: F401  (tx_time_ms, mmk_wait_ms, covered_vehicles, ...)


class MyOffloading(OffloadingPolicy):                      # variantes A, F
    def __init__(self, **kw):
        super().__init__(**kw)

    def decide(self, task, ctx):
        return "edge:nearest" if ctx.serving_ap else "local"


class MyMigration(MigrationPolicy):                        # variante B
    def decide(self, ctx):
        return None


class MyPerception(PerceptionPolicy):                      # variante C
    def choose(self, t, ctx):
        return "objects", 2.0


class MyUAV(UAVPolicy):                                    # variantes D, E, F
    def waypoint(self, t, uav, net):
        return (300.0, 20.0, 60.0)


class MyAssociation(AssociationPolicy):                    # (option) toutes variantes
    def choose(self, vid, t, current, candidates):
        return max(candidates, key=lambda a: a.snr_db).id if candidates else None
