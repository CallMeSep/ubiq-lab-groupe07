# ubiq-lab -- raccourcis. Variables : EXP=experiments/xxx.yaml BACKEND=sim|local|mininet
EXP ?= experiments/baseline.yaml
BACKEND ?= sim
PY ?= python3

# Mininet-WiFi (FACULTATIF). Version figée proposée : elle doit être validée une fois
# sur la VM de l'UE avant d'être utilisée par les étudiants (voir README, section 1.3).
MNWIFI_REF ?= 8747432
MNWIFI_DIR ?= $(HOME)/mininet-wifi

# Utilisateur à qui rendre les résultats écrits par une commande lancée avec sudo
OWNER ?= $(if $(SUDO_UID),$(SUDO_UID):$(SUDO_GID),$(shell id -u):$(shell id -g))

.PHONY: help install install-mn perms check test smoke smoke-local smoke-mn baseline baseline-mn run figs clean trace

help:
	@echo "make install        installe le coeur (backend sim) : paquets Python du systeme, via apt (sudo)"
	@echo "make check          verifie l'environnement : coeur sim (obligatoire), Mininet-WiFi (facultatif)"
	@echo "make test           tests unitaires des modeles"
	@echo "make smoke          test de fumee, backend sim (secondes)"
	@echo "make smoke-local    test de fumee, vraies applis sans emulation (~30 s)"
	@echo "make install-mn     FACULTATIF : installe Mininet-WiFi (20 a 40 min, version a valider sur la VM)"
	@echo "sudo make smoke-mn  FACULTATIF : test de fumee Mininet-WiFi (~40 s)"
	@echo "sudo make perms     rend a l'utilisateur les resultats ecrits par une commande lancee avec sudo"
	@echo "make baseline       experience commune (sim)"
	@echo "sudo make baseline-mn   experience commune (Mininet-WiFi, ~1 h : 4 variantes x 5 reps x 3 min)"
	@echo "make run EXP=experiments/group_07.yaml BACKEND=sim"
	@echo "make figs EXP=experiments/group_07.yaml"
	@echo "sudo make clean     nettoie Mininet (mn -c) et les processus restants"

# --- Coeur obligatoire (backend sim) : Python 3 + PyYAML + matplotlib, installés par apt.
# Pas d'environnement virtuel : le backend mininet tourne avec sudo et doit voir les mêmes paquets.
# (apt-get update peut échouer à cause d'un dépôt tiers indisponible : on continue avec les index existants)
install:
	-sudo apt-get update
	sudo apt-get install -y python3 python3-yaml python3-matplotlib
	@bash tools/check_env.sh

# --- FACULTATIF : Mininet-WiFi, compilé depuis les sources (hostapd, iw, Open vSwitch, Mininet).
# À lancer SANS sudo (les commandes qui en ont besoin le demandent). pip est mis à jour avant,
# car l'installeur de Mininet-WiFi utilise une option que le pip d'Ubuntu 22.04 ne connaît pas.
install-mn:
	-sudo apt-get update
	sudo apt-get install -y git python3-pip
	-sudo python3 -m pip install --upgrade pip
	[ -d "$(MNWIFI_DIR)" ] || git clone https://github.com/intrig-unicamp/mininet-wifi.git "$(MNWIFI_DIR)"
	cd "$(MNWIFI_DIR)" && git fetch --all --tags && git checkout $(MNWIFI_REF)
	cd "$(MNWIFI_DIR)" && sudo util/install.sh -Wlnfv
	@bash tools/check_env.sh

# Les commandes lancées avec sudo écrivent des fichiers appartenant à root : on les rend à l'utilisateur.
perms:
	-chown -R $(OWNER) results results_mn 2>/dev/null

check:
	@bash tools/check_env.sh

test:
	$(PY) tests/test_models.py

smoke:
	$(PY) tests/smoke_test.py --backend sim

smoke-local:
	$(PY) tests/smoke_test.py --backend local

smoke-mn:
	$(PY) tests/smoke_test.py --backend mininet; st=$$?; chown -R $(OWNER) results 2>/dev/null; exit $$st

baseline:
	$(PY) -m ubiq.run experiments/baseline.yaml --backend sim --clean && $(PY) -m ubiq.analyze experiments/baseline.yaml

baseline-mn:
	$(PY) -m ubiq.run experiments/baseline.yaml --backend mininet --clean && $(PY) -m ubiq.analyze experiments/baseline.yaml; st=$$?; chown -R $(OWNER) results 2>/dev/null; exit $$st

run:
	$(PY) -m ubiq.run $(EXP) --backend $(BACKEND)

figs:
	$(PY) -m ubiq.analyze $(EXP)

clean:
	-mn -c >/dev/null 2>&1
	-pkill -f ubiq.apps >/dev/null 2>&1
	rm -rf results/_smoke

trace:
	$(PY) tools/make_trace.py --out scenarios/traces/road_600m.csv
