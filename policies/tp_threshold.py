"""TP2, étape 4 : votre première politique d'offloading.

À compléter : ThresholdOffloading.decide(). Elle est déjà déclarée dans
experiments/tp_step0_access.yaml, tp_step3_mobility.yaml et tp_step4_freshness.yaml.
Tant que vous ne l'avez pas complétée, elle se comporte exactement comme always_edge.
Puis :
    python3 -m ubiq.run experiments/tp_step3_mobility.yaml --reps 10 --clean
    python3 -m ubiq.analyze experiments/tp_step3_mobility.yaml
"""
from policies.base import OffloadingPolicy
from policies.helpers import mmk_wait_ms, tx_time_ms  # noqa: F401  (aides autorisées, voir policies/helpers.py)


class FixedEdge(OffloadingPolicy):
    """Fournie : envoie TOUJOURS au même Edge, même quand on s'en éloigne."""
    def __init__(self, edge: str = "E1", **kw):
        super().__init__(edge=edge, **kw)
        self.edge = edge

    def decide(self, task, ctx):
        return f"edge:{self.edge}" if ctx.serving_ap else "local"


class ThresholdOffloading(OffloadingPolicy):
    """Edge si l'on estime pouvoir tenir le budget de latence, sinon local.

    decide(task, ctx) est appelée à chaque tâche ; elle renvoie 'edge:nearest' ou 'local'.
    Ce que vous recevez (attention aux unités) :

      task.input_kb, task.output_kb   tailles en ko (1 ko = 8 kbit)
      task.deadline_ms                échéance de la tâche (ms)
      ctx.t                           date courante (s, horloge de l'expérience)
      ctx.serving_ap                  AP courant, ou None (pas de couverture)
      ctx.uplink_mbps                 débit montant courant (Mb/s)
      ctx.nearest_edge                Edge le plus proche, par ex. 'E1' (None si aucun n'est joignable)
      ctx.path_delay_ms['edge:nearest']
                                      délai ONE-WAY accès + filaire vers cet Edge (ms) ;
                                      l'aller-retour vaut le double
      ctx.edge_load[nom_edge]         DERNIER RAPPORT de charge reçu pour cet Edge (absent avant
                                      le premier rapport). Champs :
          .queue                      tâches présentes dans l'Edge (attente + service) au moment du rapport
          .workers                    nombre de serveurs de calcul
          .service_ms                 temps de service par tâche (ms), ralentissement éventuel compris
          .t_report                   DATE du rapport (s) : ce n'est pas un âge
      ctx.load_age_s(nom_edge)        ÂGE de ce rapport, ctx.t - t_report (s)
      ctx.mean_latency_ms('edge:nearest', 3.0)
                                      moyenne des latences que VOUS avez observées sur les
                                      3 dernières secondes (ms), ou None
      ctx.local_service_ms            durée moyenne d'un calcul à bord (ms)
      ctx.local_queue                 tâches déjà en attente sur le calculateur de bord

    Aides autorisées (policies/helpers.py) :
      tx_time_ms(size_kb, rate_mbps)              temps d'émission (ms)
      mmk_wait_ms(queue, workers, service_ms)     attente grossière dans une file à `workers` serveurs (ms)

    Paramètres (fixés dans les fichiers d'expérience) :
      latency_budget_ms   budget de latence visé (ms)
      use_observed        False : décider uniquement à partir des rapports de charge (TODO 3 ignoré)
    """
    def __init__(self, latency_budget_ms: float = 120.0, use_observed: bool = True, **kw):
        super().__init__(latency_budget_ms=latency_budget_ms, use_observed=use_observed, **kw)
        self.budget = latency_budget_ms
        self.use_observed = use_observed

    def decide(self, task, ctx):
        if not ctx.serving_ap or ctx.nearest_edge is None or not ctx.uplink_mbps:
            return "local"
        edge = ctx.nearest_edge
     # TODO 1 : estimer le temps d'émission de la tâche vers l'Edge.
        t_tx = tx_time_ms(task.input_kb, ctx.uplink_mbps)                 

     # TODO 2 : ajouter l'aller-retour, l'attente estimée à partir du dernier rapport de charge
        #          de l'Edge le plus proche (s'il existe) et le temps de service.
        rtt = 2.0 * ctx.path_delay_ms.get("edge:nearest", 0.0)          
        rep = ctx.edge_load.get(edge)
        if rep is not None:
            wait = mmk_wait_ms(rep.queue, rep.workers, rep.service_ms)
            service = rep.service_ms
        else:
            wait, service = 0.0, 20.0
        est_edge = t_tx + rtt + wait + service

    # TODO 3 (facultatif) : si self.use_observed, tenir compte aussi des latences observées.
        if self.use_observed:                                           
            obs = ctx.mean_latency_ms("edge:nearest", 3.0)
            if obs is not None:
                est_edge = max(est_edge, obs)

        if est_edge <= self.budget:                                     # TODO 4
            return "edge:nearest"
        est_local = ctx.local_service_ms * (1 + ctx.local_queue)
        return "edge:nearest" if est_edge < est_local else "local"
