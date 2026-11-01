# Debian sur Mac Apple Silicon avec QEMU

Un laboratoire Debian ARM64 piloté par Make, avec QEMU/HVF, configuration
cloud-init, accès SSH, inventaire Ansible et snapshots disque.

Inspiré du Makefile et du script de laboratoire FreeBSD/QEMU partagés par
**ephase**. Cette adaptation cible Debian sur Mac Apple Silicon ; le script
de pilotage a été réécrit en Python.

## Utilisation

```sh
git clone https://github.com/nahsiy/debian-qemu-mac.git
cd debian-qemu-mac
make doctor
make vm_init
make ssh
```

Valeurs par défaut : Debian 13 « trixie » ARM64, 2 CPU, 2 Gio de RAM, disque
virtuel de 20 Gio (allocation à la demande), utilisateur `debian`, SSH sur
`127.0.0.1:2222`. Pas de bureau graphique : c'est une VM serveur pour les tests.

Le premier lancement télécharge environ 411 Mio et vérifie le SHA-512 publié
par Debian sur HTTPS. Ce contrôle vérifie la correspondance avec le manifeste
téléchargé ; aucune vérification de signature GPG indépendante n'est effectuée.
L'image est ensuite conservée en cache : les démarrages suivants ne consultent
pas automatiquement la nouvelle image `latest`. Les mises à jour du système
invité se font avec APT, ou en recréant le labo après suppression du cache.

Prérequis : Python 3.9 ou supérieur, QEMU avec HVF et firmware EDK2 ARM64,
`hdiutil`, OpenSSH et `curl`. Avec Homebrew, `brew install qemu python` fournit
les deux prérequis non natifs.
Aucun paquet n'est installé sur le Mac par ces scripts.

Le Makefile appelle un script Python utilisant uniquement la bibliothèque
standard. Il remplace les portions Bash dépendantes de GNU `stat`, GNU `date`
et des variantes de `nc`. L'ISO NoCloud est fabriquée avec `hdiutil` ; il n'y a
pas besoin de `cloud-localds`.

## Configuration

```sh
make vm_init VM_CPUS=4 VM_MEMORY=4096 VM_DISK_SIZE=30G
make vm_status
make vm_stop
make vm_init
```

`VM_MEMORY` est exprimé en Mio. La taille du disque s'applique à sa création ;
changer `VM_DISK_SIZE` ne redimensionne pas une VM existante. Le délai SSH et
cloud-init est borné à 300 secondes (`VM_TIMEOUT=600` pour un réseau lent).
Le firmware est détecté dans l'installation QEMU Homebrew ; il peut être fixé
avec `QEMU_FIRMWARE=/chemin/edk2-aarch64-code.fd`.

Pour plusieurs VM, conserver des noms et ports distincts :

```sh
make vm_init MACHINE_NAME=debian-deux SSH_PORT_LOCAL=2223
make ssh MACHINE_NAME=debian-deux SSH_PORT_LOCAL=2223
make vm_stop MACHINE_NAME=debian-deux SSH_PORT_LOCAL=2223
```

Réutiliser les mêmes paramètres pour les commandes suivantes, notamment le
port et l'utilisateur. Les modèles cloud-init sont dans `vm_config/user-data`
et `vm_config/meta-data`.
Les marqueurs `__SSH_USER__` et `__SSH_PUBLIC_KEY__` sont remplacés automatiquement.
Il installe Python 3 et sudo dans l'invité, autorise sudo sans mot de passe
pour l'utilisateur de labo et désactive l'authentification SSH par mot de passe.
Modifier ce modèle s'applique à une nouvelle VM ; cloud-init n'est pas relancé
à chaque démarrage. Ne pas y écrire de secrets.

Le modèle `meta-data` fournit `instance-id` et `local-hostname`. Les marqueurs
`__INSTANCE_ID__` et `__MACHINE_NAME__` sont remplacés par un identifiant stable
pour cette VM et son nom. Les deux fichiers rendus sont consultables dans
`.vm/machines/<nom>/cloud-init/` ; ils sont intégrés à l'ISO `seed.iso`, au
label `cidata`. La clé privée n'est jamais placée dans l'ISO.

Les modèles versionnés ne contiennent aucune clé réelle. Les images, clés,
inventaires et fichiers cloud-init rendus restent sous `.vm/`, exclu de Git.

Chaque VM possède sa propre clé SSH jetable et son propre `known_hosts`, sous
`.vm/machines/<nom>/`. Le premier contact utilise `accept-new`, les contacts
suivants vérifient la clé mémorisée. Les configurations et clés de `~/.ssh`
ne sont pas modifiées. QEMU n'expose SSH que sur la boucle locale du Mac.
L'invité dispose d'une sortie réseau via le réseau utilisateur QEMU.

## Snapshots disque

```sh
make vm_create_snapshot SNAPSHOT=base
# Faire ses essais dans la VM.
make vm_restore_snapshot SNAPSHOT=base
```

Ces commandes arrêtent proprement une VM démarrée, créent ou restaurent le
snapshot QCOW2 puis la redémarrent. Une VM initialement arrêtée reste arrêtée.
La mémoire vive n'est pas sauvegardée. Restaurer un snapshot efface les
changements faits sur le disque depuis sa création. L'image et la configuration
matérielle doivent rester compatibles : ce n'est pas une sauvegarde externe.

Pour lister les snapshots :

```sh
make vm_stop
make vm_snapshots
make vm_init
```

L'arrêt utilise le protocole QMP et attend la fin de QEMU ; aucun `kill -9`
n'est utilisé. Un échec d'arrêt bloque la suppression et les snapshots.

## Ansible et Molecule

L'inventaire JSON Ansible est généré sous `.vm/machines/debian-test/inventory.json` :

```sh
ansible -i .vm/machines/debian-test/inventory.json all -m ping
ansible -i .vm/machines/debian-test/inventory.json all -b -m command -a 'id -u'
```

Pour un rôle possédant déjà un scénario Molecule adapté à une VM externe :

```sh
make test ROLE=/chemin/vers/roles/mon_role
```

La commande vérifie la présence du scénario et de Molecule, prépare la VM,
puis exporte `DEBIAN_VM_INVENTORY` avec le chemin de l'inventaire avant de lancer
`molecule test` dans le rôle. **Le scénario doit explicitement utiliser cet
inventaire et laisser le cycle de vie de la VM à ce laboratoire.** Cette variable
n'est pas une option native de Molecule. La commande n'adapte pas un scénario
Docker existant et ne crée pas un scénario absent.

Molecule n'est pas installé automatiquement. Le scénario propre à ton rôle
reste à configurer ; l'inventaire peut déjà servir directement avec Ansible.

## Suppression et diagnostic

```sh
make vm_destroy  # Arrête et supprime cette VM, ses snapshots et sa clé.
make clean       # Supprime tout .vm, y compris le cache ; refuse une VM active.
```

`vm_destroy` conserve l'image téléchargée. Une copie disque indépendante permet
de recréer la VM sans retélécharger l'image et sans disque de base partagé.

En cas de délai dépassé, la VM est conservée pour diagnostic. La console série
du dernier démarrage est dans `.vm/machines/<nom>/console.log`.
Si SSH fonctionne, contrôler aussi `sudo cloud-init status --long` et
`sudo journalctl -u cloud-final` dans l'invité.

## Sources

- [Images officielles Debian](https://cloud.debian.org/images/cloud/trixie/latest/)
- [QEMU ARM virt](https://www.qemu.org/docs/master/system/arm/virt.html)
- [Cloud-init NoCloud](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html)

## Vérifications sur ce Mac

Vérifications du 1er novembre 2026 sur macOS 27.2 ARM64, QEMU 11.1.1 :

- Téléchargement de l'image et comparaison SHA-512 : réussis.
- Démarrage Debian 13.7, noyau `aarch64`, accélération HVF : réussis.
- ISO NoCloud détectée sur `/dev/vdb`, `cloud-init status --long` : `done`, aucune erreur.
- Partition racine automatiquement portée à 20 Gio : vérifiée dans l'invité.
- Connexion par la clé dédiée et exécution sudo : réussies.
- Ansible `ping` : `pong`, y compris après restauration du snapshot ; `id -u` avec élévation : `0`.
- Snapshot disque créé, VM redémarrée, fichier témoin créé, snapshot restauré,
  fichier témoin absent : restauration vérifiée.
- Arrêt propre, redémarrage immédiat et `qemu-img check` : réussis.
- Refus de `clean` sur une VM active et refus d'un snapshot sans nom : vérifiés.
- Une expiration SSH individuelle ne supprime pas le délai global de disponibilité : vérifié.

Le contrôle de port a été corrigé après un faux positif lié à `TIME_WAIT` lors
du premier redémarrage immédiat. Aucun service n'écoutait alors sur le port.
Une première sonde Ansible lancée avec d'autres connexions simultanées a reçu
un reset SSH ; les sondes séquentielles et celle après restauration ont réussi.
La cause de ce reset isolé n'a pas été établie.

Non vérifiés : scénario Molecule (absent, outil non installé), exécution de tes
rôles, autre Mac/version de QEMU, charge soutenue et plusieurs VM simultanées.
