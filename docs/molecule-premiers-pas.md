# Premier exercice Molecule : un serveur Nginx

L'objectif est de répondre à trois questions différentes : le rôle s'applique-t-il,
peut-on le rejouer sans modification inutile, et le serveur obtenu fonctionne-t-il ?

## 1. Comprendre les fichiers avant de lancer

```text
roles/nginx_demo/
├── defaults/main.yml               Le message configurable du rôle
├── tasks/main.yml                  Les trois tâches du rôle
├── templates/index.html.j2         La page HTML à publier
└── molecule/default/
    ├── molecule.yml                La cible et la séquence de test
    ├── converge.yml                Le playbook qui appelle le rôle
    └── verify.yml                  Les observations et assertions
```

Le **rôle** installe Nginx, dépose une page et active le service.
Le **scénario** applique ce rôle puis contrôle son résultat.
Le rôle peut servir dans un autre playbook sans Molecule ; les fichiers du
scénario restent spécifiques au test.

Dans ce labo, les responsabilités sont réparties ainsi :

```text
Make → script Python → QEMU → VM Debian + cloud-init
Make → Molecule → Ansible → SSH vers cette VM → rôle puis vérifications
```

Molecule utilise le groupe `debian_lab` de l'inventaire généré par le script.
Il ne crée ni ne détruit la VM dans ce scénario. Le test complet conserve donc
Nginx installé et la VM démarrée. Ce choix permet d'inspecter le résultat.

## 2. Préparer le contrôleur et la cible

Depuis la racine du dépôt, avec Python 3.12 ou supérieur :

```sh
make tools
make vm_init
```

`make tools` installe les versions de `requirements-dev.txt` dans `.venv/` sur
le **Mac**. `make vm_init` prépare **Debian**, qui est la machine cible.
Les outils de développement ne sont pas installés globalement.

Les commandes Make sélectionnent automatiquement `.venv` : aucune activation
manuelle n'est nécessaire. Pour choisir un autre Python lors de l'installation :

```sh
make tools VENV_PYTHON=python3.12
```

## 3. Converge : appliquer le rôle

```sh
make molecule-converge
```

Cette commande prépare la VM si nécessaire, puis exécute `molecule converge`
depuis `roles/nginx_demo`. `converge.yml` appelle le rôle avec `become: true`
pour obtenir les droits sudo dans Debian.

À la première application, l'installation et la page doivent normalement
produire des tâches `changed`. Le service peut déjà être démarré par le paquet
Debian : sa tâche peut donc afficher `ok` dès ce premier passage.

Dans le récapitulatif Ansible :

- `ok` : tâches réussies, y compris celles qui ont changé quelque chose ;
- `changed` : sous-ensemble ayant effectivement modifié la cible ;
- `failed=0` : aucune tâche n'a échoué.

Si le labo a déjà servi, Nginx peut être présent et le premier passage que tu
lances peut déjà afficher `changed=0`. C'est normal : le rôle décrit un état.

## 4. Idempotence : rejouer sans changement

Après converge :

```sh
make molecule-idempotence
```

Molecule rejoue le même `converge.yml` et contrôle les changements rapportés
par Ansible. Le résultat attendu est `changed=0`, puis un succès d'idempotence.
Les tâches sont exécutées : elles constatent que le paquet, le fichier et le
service sont déjà conformes.

Cela vérifie le comportement de ce rôle dans cet état. Cela ne démontre pas
qu'il est correct dans toutes les situations possibles.

Dans `verify.yml`, `changed_when: false` accompagne `nginx -t` parce que cette
commande ne fait qu'observer la configuration. Il ne faut pas ajouter ce
réglage à une tâche qui modifie réellement le système pour cacher une erreur
d'idempotence.

## 5. Verify : vérifier le résultat utile

```sh
make molecule-verify
```

Le playbook de vérification contrôle que :

- Nginx est en cours d'exécution et activé au démarrage ;
- `nginx -t` accepte sa configuration ;
- la page existe avec les permissions attendues ;
- une vraie requête HTTP répond avec le code 200 et le message du scénario.

La requête vers `http://127.0.0.1/` est effectuée **dans Debian**, via Ansible.
Cette adresse ne désigne donc pas le Mac. Seul SSH est redirigé vers le Mac
dans la configuration QEMU actuelle.

Le message attendu est écrit explicitement dans le scénario : si tu changes
la variable du rôle, le test de contenu échouera jusqu'à ce que tu ajustes
également l'attente du scénario. Cela permet de vérifier un résultat précis.

## 6. Observer un échec utile

Un test qui passe n'est instructif que si l'on comprend ce qu'il détecte.
Arrête volontairement le service dans la VM de labo :

```sh
make ssh
sudo systemctl stop nginx
exit
```

Puis, depuis le Mac :

```sh
make molecule-verify
```

Cette commande doit échouer sur l'assertion « Nginx doit être démarré et activé
au boot ». **Verify ne répare pas le service.** Le rôle a pu réussir auparavant,
mais l'état actuel du système n'est plus celui attendu.

Répare ensuite en rejouant le rôle, puis vérifie à nouveau :

```sh
make molecule-converge
make molecule-idempotence
make molecule-verify
```

La réparation doit signaler un changement sur le démarrage du service.
Le passage d'idempotence suivant doit revenir à zéro changement.

## 7. Exécuter le scénario complet

```sh
make test
```

Le scénario livré exécute précisément :

```text
converge → idempotence → verify
```

Il ne repart pas automatiquement d'une Debian vierge. Pour tester une première
installation, utilise une nouvelle VM dédiée ou restaure un snapshot créé
avant l'installation de Nginx. Par exemple :

```sh
make vm_init MACHINE_NAME=molecule-propre SSH_PORT_LOCAL=2223
make vm_create_snapshot MACHINE_NAME=molecule-propre SSH_PORT_LOCAL=2223 SNAPSHOT=avant-nginx
make test MACHINE_NAME=molecule-propre SSH_PORT_LOCAL=2223
make vm_stop MACHINE_NAME=molecule-propre SSH_PORT_LOCAL=2223
```

Pour arrêter la VM principale après tes essais : `make vm_stop`.

## Et le mode Ansible --check ?

Le mode check estime les changements sans appliquer les mutations prises en
charge par les modules. Son résultat dépend du support du module et des données
disponibles ; il ne permet pas de savoir si un service encore absent démarrera.

Ici, converge applique les modifications ; idempotence rejoue réellement le
rôle ; verify observe le service et sa réponse HTTP. Les deux approches peuvent
être utilisées ensemble pour répondre à des questions différentes.

## Lancer Molecule directement, pour voir les commandes

Les raccourcis Make ajoutent le chemin de l'inventaire et sélectionnent le
bon environnement. L'équivalent manuel, depuis la racine du dépôt, est :

```sh
make vm_init
export DEBIAN_VM_INVENTORY="$(pwd)/.vm/machines/debian-test/inventory.json"
. .venv/bin/activate
cd roles/nginx_demo
molecule converge
molecule idempotence
molecule verify
# Ou molecule test pour toute la séquence.
```

`DEBIAN_VM_INVENTORY` est une convention de ce labo : `molecule.yml` la lit
explicitement pour passer `--inventory` à Ansible.

## Références

- [Tester un rôle avec Molecule](https://docs.ansible.com/projects/molecule/getting-started-roles/)
- [Configuration Ansible native](https://docs.ansible.com/projects/molecule/ansible-native/)
- [Actions et séquences Molecule](https://docs.ansible.com/projects/molecule/workflow/)
