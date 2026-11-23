# ubiq-lab — Systèmes ubiquitaires (Edge, Vehicular, UAV)

Environnement de TP et de projet de l'UE *Systèmes ubiquitaires* du M2 RSA (Université Paris Cité).

Il modélise des véhicules qui se déplacent le long d'une route, des points d'accès au sol, des serveurs Edge, un Cloud et un drone (UAV). Ce drone peut servir de point d'accès ou d'Edge mobile.

**Vous n'écrivez que des *politiques*** (où calculer, que transmettre, où placer le drone…). L'environnement se charge du reste : mobilité, pannes, réseau, mesures, figures.

```
            Cloud                       mobilité SUBIE   : les véhicules suivent une trace
              |  20 ms                  mobilité PILOTÉE : le drone suit VOTRE politique
     E1 --- [S1] ------- [S2] --- E2
          /    \    5 ms   |
       AP1     AP2        AP3           (AP2 tombe à t = 60 s)
        )))     )))        )))
     V4 V5    V1 V3      V2 V6  →       6 véhicules, 2 sens, un feu rouge au milieu
                 \
                 UAV  (x, y, h)          décolle à t = 75 s, backhaul sans fil vers AP1
```

## 1. Installation et démarrage

Point de départ : une VM Ubuntu 22.04 sans rien d'autre, et l'archive `ubiq-lab.zip` fournie avec le sujet, enregistrée dans votre dossier personnel. Toutes les commandes se lancent depuis un terminal ; celles qui installent des paquets demandent votre mot de passe (`sudo`).

### 1.1 Cœur obligatoire : backend `sim` (quelques minutes)

```bash
sudo apt update && sudo apt install -y unzip make   # outils nécessaires
cd ~ && unzip ubiq-lab.zip && cd ubiq-lab
make install            # python3, PyYAML, matplotlib, via apt (paquets du système)
make check              # verdict : « cœur sim : OK »
make test               # modèles (canal, énergie, graphe)
make smoke              # 20 s simulées en 1 s -> SMOKE OK
```

Les dépendances Python sont installées par `apt`, sans environnement virtuel : le backend `mininet` tourne avec `sudo`, et doit voir les mêmes paquets que vous. Le backend `sim` suffit pour réaliser le TP2 et pour développer le projet.

### 1.2 Facultatif : Mininet-WiFi (20 à 40 min de compilation)

```bash
make install-mn         # à lancer SANS sudo ; compile hostapd, iw, Open vSwitch, Mininet, Mininet-WiFi
make check              # verdict : « Mininet-WiFi : disponible » ?
sudo make smoke-mn      # environ 40 s -> SMOKE OK
```

**Attention : cette installation n'est pas garantie.** La version figée de Mininet-WiFi (`MNWIFI_REF` dans le `Makefile`) doit d'abord être validée une fois sur la VM de l'UE par l'enseignant. Elle dépend aussi du noyau de la VM : sans le module `mac80211_hwsim` (`modinfo mac80211_hwsim`), le backend `mininet` ne peut pas fonctionner. Si l'installation échoue, continuez avec le backend `sim` : rien d'obligatoire n'en dépend. Sur certaines VM, il faut en plus arrêter NetworkManager pendant les runs Mininet (`sudo systemctl stop NetworkManager`).

### 1.3 Commandes lancées avec `sudo`

Les runs Mininet (`sudo ...`) écrivent des fichiers qui appartiennent à root. `sudo make smoke-mn` vous les rend automatiquement ; après tout autre run lancé avec `sudo`, faites `sudo make perms` avant d'analyser ou de relancer sans `sudo`.

## 2. Trois backends, une seule API

| Backend | Commande | Quand l'utiliser |
|---|---|---|
| `sim` | `python3 -m ubiq.run EXP` | Développer et déboguer. Plus rapide que le temps réel, fonctionne sur n'importe quel portable. |
| `local` | `python3 -m ubiq.run EXP --backend local` | Vérifier que vos politiques tournent dans les vraies applications (TCP, processus), sans émulation réseau. |
| `mininet` | `sudo python3 -m ubiq.run EXP --backend mininet` | **Figures finales.** Vraies piles réseau, vraies associations Wi-Fi, vraies files d'attente. Tourne en temps réel : un run de 180 s dure 3 min. |

Les politiques, les scénarios et le format des résultats sont **identiques** dans les trois backends.

## 3. Ce que vous modifiez (et rien d'autre)

```
policies/group_<n>.py        vos politiques           (copie de policies/group_XX.py)
experiments/group_<n>.yaml   votre plan d'expériences (copie de experiments/group_XX.yaml)
```

`ubiq/`, `scenarios/` et `policies/baselines.py` sont communs à la promotion. **Ne les modifiez pas.** Si vous pensez devoir le faire, c'est une question à poser à l'enseignant. Pour changer un paramètre du scénario, utilisez `overrides:` dans votre fichier d'expérience.

### Les cinq politiques (voir `policies/base.py`)

| Politique | Qui décide | Échelle de temps | Méthode | Variante |
|---|---|---|---|---|
| `OffloadingPolicy` | véhicule | chaque tâche (~200 ms) | `decide(task, ctx)` → `'local'`, `'edge:nearest'`, `'edge:E2'`, `'cloud'`, `'service'` | A, F |
| `MigrationPolicy` | orchestrateur | chaque tick (100 ms) | `decide(ctx)` → id d'Edge ou `None` | B |
| `PerceptionPolicy` | véhicule | chaque mise à jour | `choose(t, ctx)` → (`'raw'`, `'features'` ou `'objects'`, Hz) | C |
| `UAVPolicy` | opérateur | chaque tick | `waypoint(t, uav, net)` → `(x, y, h)` | D, E, F |
| `AssociationPolicy` | réseau | chaque tick | `choose(vid, t, current, candidates)` → id d'AP | option |

Le contexte `ctx` (`ubiq/ctx.py`) ne contient **que ce qu'un vrai véhicule pourrait savoir**. Par exemple, la charge des Edge arrive par des rapports périodiques (`t_report`) : **l'information de contrôle a elle-même un âge**, et un Edge en panne cesse simplement d'envoyer ses rapports.

## 4. Lancer une expérience et produire les figures

```bash
python3 -m ubiq.run experiments/group_07.yaml               # sim
sudo python3 -m ubiq.run experiments/group_07.yaml --backend mininet
python3 -m ubiq.analyze experiments/group_07.yaml           # tableaux + figures
```

Les figures sont écrites dans `results/<exp>/figures/`. Les trois figures obligatoires du rapport sont :

1. **l'architecture** : dessinée par vous ;
2. **la baseline** : `results/baseline/figures/fig_phases.pdf` ;
3. **la comparaison** : `results/group_<n>/figures/fig_phases.pdf` ou `fig_sweep.pdf`.

`make figs EXP=...` doit **régénérer** vos figures à partir de `results/`. C'est vérifié en soutenance.

## 5. Fichiers produits par run

`results/<exp>/<variante>/<valeur balayée>/rep<k>/` contient :

| Fichier | Contenu |
|---|---|
| `tasks.csv` | une ligne par tâche : cible, nœud, latence, statut (`ok`, `late`, `fail_*`), phase |
| `perception.csv` | une ligne par mise à jour de perception |
| `aoi.csv` | âge de l'information par véhicule (ms), échantillonné |
| `ticks.csv` | positions, AP servant, SNR, débit (toutes les 0,5 s) |
| `events.csv` | pannes, handovers, migrations, UAV… |
| `uav.csv` | trajectoire, puissance de propulsion, énergie, véhicules servis |

## 6. Ce que l'environnement représente, et ce qu'il ne représente pas

- Le **canal radio** est un modèle simple (`ubiq/channel.py`) : log-distance au sol, Al-Hourani (2014) pour le lien air-sol. Mininet-WiFi transporte les vrais paquets, mais **la qualité des liens vient du modèle**.
- Le **calcul** est émulé : un temps de service tiré autour d'une moyenne. Les files d'attente, elles, sont réelles.
- La **« précision »** des représentations de perception est un paramètre fictif, assumé comme tel.
- Conclusion : comparez des politiques entre elles. **N'interprétez pas les valeurs absolues comme celles d'un vrai réseau V2X ou 5G.**

## 7. Dépannage

| Symptôme | Solution |
|---|---|
| `RTNETLINK answers: File exists`, Mininet bloqué | `sudo make clean` |
| run Mininet interrompu (Ctrl-C) | `sudo make clean`, puis relancer |
| « ticks en retard » | machine trop chargée : fermez les autres applications, réduisez `vehicles.count` |
| une politique lève une exception | l'agent choisit `local` et l'écrit dans `results/.../_rt/agent_V*.log` |
| figures absentes | `python3 -m ubiq.analyze <exp>` après le run |
| `Permission denied` dans `results/` ou `results_mn/` | un run a été lancé avec `sudo` : `sudo make perms` |
