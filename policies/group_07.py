"""Politiques du groupe NN -- variante C (Perception coopérative).

QUESTION
  En choisissant à chaque mise à jour la représentation ET la fréquence qui maximisent
  « précision - lambda x âge attendu », sous la contrainte de ne pas prendre aux tâches de
  calcul la bande montante dont elles ont besoin, peut-on à la fois augmenter la précision
  livrée et réduire l'AoI, sans dégrader le taux de succès des tâches ?

CRITÈRE (le piège de la fiche : ne pas optimiser l'âge seul ni la précision seule)
  Utilité d'une option (repr, f) :   U = précision(repr) - lambda * AoI_attendu(repr, f)  [AoI en s]
  lambda = « prix de l'âge » : combien de précision on accepte de perdre pour 1 s de fraîcheur.
  Avec lambda = 1 : passer de 'objects' (0,80) à 'features' (0,93) vaut le coup si cela coûte
  moins de 130 ms d'âge supplémentaire.
  Contrainte : charge(perception) + charge(tâches) <= marge x part de bande du véhicule.
  Les tâches sont prioritaires : elles ont une échéance dure (150 ms).

CE QUE LA POLITIQUE SAIT AU MOMENT DE DÉCIDER (et avec quel âge)
  ctx.uplink_mbps           débit radio courant (instantané)
  ctx.aps_in_range[].n_assoc nombre de véhicules sur l'AP servant (instantané)
  ctx.path_delay_ms         délai one-way vers l'Edge le plus proche
  ctx.history               résultats de SES tâches : on en déduit SON débit de tâches envoyées
                            sur la radio (fenêtre de 2 s), sans connaître le scénario
  ctx.mean_latency_ms       latence de SES tâches récentes : garde-fou si la radio sature
  Tailles, temps de prétraitement et précisions des représentations : connues de
  l'application (copiées du scénario dans les paramètres).

AoI ATTENDU d'une option (repr, f)
  1/(2f)            attente moyenne entre deux mises à jour
  + pre_ms          prétraitement à bord
  + taille / débit  émission
  + délai one-way   jusqu'à l'Edge
  + fusion_ms       fusion à l'Edge
"""
from policies.base import PerceptionPolicy

# Représentations (copie des valeurs du scénario : c'est l'application qui les connaît)
DEFAULT_REPRS = {
    "raw":      {"size_kb": 600, "pre_ms": 5,  "fusion_ms": 30, "accuracy": 1.00},
    "features": {"size_kb": 80,  "pre_ms": 25, "fusion_ms": 10, "accuracy": 0.93},
    "objects":  {"size_kb": 4,   "pre_ms": 45, "fusion_ms": 2,  "accuracy": 0.80},
}
DEFAULT_MENU = [["objects", 2], ["objects", 4], ["features", 2], ["features", 4], ["raw", 1]]


class AdaptivePerception(PerceptionPolicy):
    """Choisit (représentation, fréquence) qui maximise précision - lambda x AoI attendu,
    parmi les options dont la charge tient dans la bande laissée par les tâches.

    Paramètres (YAML) :
      lam               prix de l'âge (précision perdue par seconde d'AoI)
      margin            fraction de la part de bande utilisable (le reste absorbe les rafales)
      ap_capacity_mbps  capacité d'un AP (25 Mb/s dans le scénario)
      task_kb           taille d'une tâche (connue de l'application)
      rate_window_s     fenêtre de mesure du débit de tâches envoyées
      lat_guard_ms      si la latence moyenne de mes tâches distantes dépasse ce seuil,
                        la radio sature : je me rabats sur l'option la plus légère
      menu              options (repr, Hz) autorisées
      reprs             tailles / précisions des représentations
      fallback          option sans couverture (rien ne sera livré : on reste léger)
    """

    def __init__(self, lam: float = 1.0, margin: float = 0.7, ap_capacity_mbps: float = 25.0,
                 task_kb: float = 120.0, rate_window_s: float = 2.0, lat_guard_ms: float = 110.0,
                 menu=None, reprs=None, fallback=("objects", 2.0), **kw):
        menu = [list(m) for m in (menu or DEFAULT_MENU)]
        reprs = dict(reprs or DEFAULT_REPRS)
        super().__init__(lam=lam, margin=margin, ap_capacity_mbps=ap_capacity_mbps, task_kb=task_kb,
                         rate_window_s=rate_window_s, lat_guard_ms=lat_guard_ms, menu=menu,
                         reprs=reprs, fallback=list(fallback), **kw)
        self.lam = float(lam)
        self.margin = float(margin)
        self.cap = float(ap_capacity_mbps)
        self.task_kb = float(task_kb)
        self.win = float(rate_window_s)
        self.guard = float(lat_guard_ms)
        self.menu = [(str(r), float(f)) for r, f in menu]
        self.reprs = reprs
        self.fallback = (str(fallback[0]), float(fallback[1]))
        self.last_choice = None     # pour le journal / le débogage uniquement

    # -------------------------------------------------------------- mesures locales
    def task_mbps(self, ctx):
        """Débit montant de MES tâches distantes, mesuré sur ma fenêtre récente."""
        n = 0
        for key, h in ctx.history.items():
            if key == "local" or key.startswith("node:"):
                continue
            n += sum(1 for (t, lat, st) in h if 0 <= ctx.t - t <= self.win)
        return n / self.win * self.task_kb * 8 / 1000.0

    def my_share_mbps(self, ctx):
        """Ma part de la bande : min(mon débit radio, capacité AP / véhicules associés)."""
        ap = next((a for a in ctx.aps_in_range if a.id == ctx.serving_ap), None)
        n = max(1, ap.n_assoc) if ap else 1
        return min(ctx.uplink_mbps, self.cap / n)

    # -------------------------------------------------------------- modèle d'option
    def load_mbps(self, repr_, f):
        return self.reprs[repr_]["size_kb"] * 8 * f / 1000.0

    def expected_aoi_s(self, ctx, repr_, f, share):
        r = self.reprs[repr_]
        one_way = ctx.path_delay_ms.get("edge:nearest", 20.0)
        if one_way != one_way or one_way == float("inf"):
            one_way = 20.0
        tx_ms = r["size_kb"] * 8 / max(share, 1e-3)
        return (1.0 / (2 * f)) + (r["pre_ms"] + tx_ms + one_way + r["fusion_ms"]) / 1000.0

    def utility(self, ctx, repr_, f, share):
        return self.reprs[repr_]["accuracy"] - self.lam * self.expected_aoi_s(ctx, repr_, f, share)

    # -------------------------------------------------------------- décision
    def choose(self, t, ctx):
        if not ctx.serving_ap or ctx.uplink_mbps <= 0:
            self.last_choice = self.fallback
            return self.fallback
        share = self.my_share_mbps(ctx)
        budget = self.margin * share - self.task_mbps(ctx)

        # garde-fou : mes tâches distantes sont déjà lentes -> radio saturée
        lat = ctx.mean_latency_ms("edge:nearest", self.win)
        congested = lat is not None and lat > self.guard

        feasible = [(r, f) for (r, f) in self.menu
                    if not congested and self.load_mbps(r, f) <= max(budget, 0.0)]
        if not feasible:
            # option la plus légère du menu, à la fréquence qui minimise l'AoI attendu
            light = min(self.menu, key=lambda o: (self.load_mbps(*o) / o[1], -o[1]))
            lightest = [o for o in self.menu if o[0] == light[0]]
            choice = min(lightest, key=lambda o: self.load_mbps(*o)) if congested else \
                max(lightest, key=lambda o: o[1])
        else:
            choice = max(feasible, key=lambda o: self.utility(ctx, o[0], o[1], share))
        self.last_choice = choice
        return choice
