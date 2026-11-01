.DEFAULT_GOAL := help
.NOTPARALLEL:

PYTHON ?= python3
MACHINE_NAME ?= debian-test
SSH_PORT_LOCAL ?= 2222
SSH_USER ?= debian
VM_CPUS ?= 2
VM_MEMORY ?= 2048
VM_DISK_SIZE ?= 20G
VM_TIMEOUT ?= 300
SNAPSHOT ?=
ROLE ?=

export MACHINE_NAME SSH_PORT_LOCAL SSH_USER VM_CPUS VM_MEMORY VM_DISK_SIZE VM_TIMEOUT SNAPSHOT ROLE

.PHONY: help doctor vm_init vm_stop vm_status vm_destroy vm_create_snapshot vm_restore_snapshot vm_snapshots ssh inventory test clean

help:
	@echo 'make doctor                       Vérifier les prérequis'
	@echo 'make vm_init                      Créer/démarrer Debian et attendre cloud-init'
	@echo 'make ssh                          Se connecter à la VM'
	@echo 'make inventory                    Afficher le chemin de l’inventaire Ansible'
	@echo 'make vm_status                    Afficher l’état de la VM'
	@echo 'make vm_stop                      Arrêter proprement Debian'
	@echo 'make vm_create_snapshot SNAPSHOT=base   Snapshot disque avec arrêt/redémarrage'
	@echo 'make vm_restore_snapshot SNAPSHOT=base  Restaurer le disque (efface les changements suivants)'
	@echo 'make vm_snapshots                 Lister les snapshots disque'
	@echo 'make test ROLE=roles/mon_role      Lancer un scénario Molecule configuré pour cette VM'
	@echo 'make vm_destroy                   Supprimer cette VM en conservant le cache image'
	@echo 'make clean                        Effacer .vm si toutes les VM sont arrêtées'

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

clean:
	@$(PYTHON) scripts/debian_vm.py clean
