.DEFAULT_GOAL := help
.NOTPARALLEL:

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
VENV_PYTHON ?= python3
MACHINE_NAME ?= debian-test
SSH_PORT_LOCAL ?= 2222
SSH_USER ?= debian
VM_CPUS ?= 2
VM_MEMORY ?= 2048
VM_DISK_SIZE ?= 20G
VM_TIMEOUT ?= 300
SNAPSHOT ?=
ROLE ?= roles/nginx_demo

export MACHINE_NAME SSH_PORT_LOCAL SSH_USER VM_CPUS VM_MEMORY VM_DISK_SIZE VM_TIMEOUT SNAPSHOT ROLE

.PHONY: help tools doctor vm_init vm_stop vm_status vm_destroy vm_create_snapshot vm_restore_snapshot vm_snapshots ssh inventory test molecule-converge molecule-idempotence molecule-verify clean

help:
	@echo 'make tools                        Installer Ansible/Molecule dans .venv (Python 3.12+)'
	@echo 'make doctor                       Vérifier les prérequis'
	@echo 'make vm_init                      Créer/démarrer Debian et attendre cloud-init'
	@echo 'make ssh                          Se connecter à la VM'
	@echo 'make inventory                    Afficher le chemin de l’inventaire Ansible'
	@echo 'make vm_status                    Afficher l’état de la VM'
	@echo 'make vm_stop                      Arrêter proprement Debian'
	@echo 'make vm_create_snapshot SNAPSHOT=base   Snapshot disque avec arrêt/redémarrage'
	@echo 'make vm_restore_snapshot SNAPSHOT=base  Restaurer le disque (efface les changements suivants)'
	@echo 'make vm_snapshots                 Lister les snapshots disque'
	@echo 'make molecule-converge            Appliquer le rôle nginx_demo'
	@echo 'make molecule-idempotence         Rejouer et vérifier zéro changement'
	@echo 'make molecule-verify              Vérifier le service, la configuration et la page'
	@echo 'make test                         Converge → idempotence → verify pour nginx_demo'
	@echo 'make test ROLE=roles/mon_role      Tester un autre rôle configuré pour cette VM'
	@echo 'make vm_destroy                   Supprimer cette VM en conservant le cache image'
	@echo 'make clean                        Effacer .vm si toutes les VM sont arrêtées'

tools:
	@$(VENV_PYTHON) -c 'import sys; assert sys.version_info >= (3, 12), "Molecule : utiliser Python 3.12+ via VENV_PYTHON"'
	@$(VENV_PYTHON) -m venv .venv
	@.venv/bin/python -m pip install -r requirements-dev.txt

doctor:
	@$(PYTHON) scripts/debian_vm.py doctor

vm_init:
	@$(PYTHON) scripts/debian_vm.py init

vm_stop:
	@$(PYTHON) scripts/debian_vm.py stop

vm_status:
	@$(PYTHON) scripts/debian_vm.py status

vm_destroy:
	@$(PYTHON) scripts/debian_vm.py destroy

vm_create_snapshot:
	@$(PYTHON) scripts/debian_vm.py create_snapshot

vm_restore_snapshot:
	@$(PYTHON) scripts/debian_vm.py restore_snapshot

vm_snapshots:
	@$(PYTHON) scripts/debian_vm.py snapshots

ssh:
	@$(PYTHON) scripts/debian_vm.py ssh

inventory:
	@$(PYTHON) scripts/debian_vm.py inventory

test:
	@$(PYTHON) scripts/debian_vm.py test

molecule-converge:
	@$(PYTHON) scripts/debian_vm.py converge

molecule-idempotence:
	@$(PYTHON) scripts/debian_vm.py idempotence

molecule-verify:
	@$(PYTHON) scripts/debian_vm.py verify

clean:
	@$(PYTHON) scripts/debian_vm.py clean
