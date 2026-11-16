# Mirivue — dépôt Pacman pour Arch Linux et CachyOS

**Le dépôt signé est publié.** La première publication, les signatures et
l'installation simultanée des deux éditions ont réussi :
[exécution de référence](https://github.com/denamiel/mirivue-arch/actions/runs/41141962504).
Les paquets actuels sont dans la
[publication `repository`](https://github.com/denamiel/mirivue-arch/releases/tag/repository).

Le dépôt fournit des préversions. Les réglages de publication restent sous le
contrôle du propriétaire ; une suspension ou un échec bloque les nouvelles
publications sans retirer les paquets déjà disponibles.

Ce dépôt héberge le mécanisme de distribution de deux paquets indépendants :

- `mirivue-gnome` : GTK4, libadwaita et GIO, sans dépendance KDE/Qt ;
- `mirivue-kde` : Qt/KDE et ses composants natifs.

Les recettes et licences des deux applications restent dans leurs dépôts amont.
Les dépendances KDE ne sont pas ajoutées au paquet GNOME. Installer une édition
ne choisit pas automatiquement le gestionnaire de fichiers par défaut.

## Fonctionnement

Le workflow central examine les branches `main` des deux projets publics. Il
ne retient un commit que si son workflow requis a réussi sur ce même commit.
Les références sont ensuite figées par SHA pour la construction.

Les éditions sont indépendantes : seuls les numéros de version explicitement
augmentés et validés sur leur commit de `main` sont reconstruits. KDE exige ses
contrôles Fedora et Arch ; GNOME exige ses contrôles dédiés. Les paquets inchangés
restent dans le catalogue, avec leurs sources et signatures vérifiées.

Les validations utilisent une clé éphémère de test. Le job de publication seul
reçoit la clé du propriétaire et l’autorisation d’écriture. Il exige une branche
`main` protégée, une PR, le contrôle **Validation du dépôt signé**, des sources
encore valides et un manifeste de départ inchangé.

Chaque heure, le workflow publie automatiquement les nouvelles versions validées
lorsque `PUBLISH_ENABLED=true`. Les PR ne peuvent rien publier. Une modification
sans hausse de version amont ne publie rien et n’augmente plus artificiellement
la révision de l’autre édition. Un candidat jetable peut être construit pour
vérifier les modifications du circuit lui-même ; il ne peut jamais être publié.

Une reprise manuelle peut sélectionner une seule édition :

```bash
gh workflow run repository.yml --repo denamiel/mirivue-arch --ref main -f edition=kde
```

L’environnement `publication-pacman` reste limité à `main`, sans approbation
manuelle supplémentaire. La fusion d’une nouvelle version validée constitue
la décision de publication. `PUBLISH_ENABLED=false` permet de suspendre les
publications sans retirer les paquets déjà disponibles.

## Publication et conservation

Les fichiers publics sont servis par la publication GitHub `repository` :

`https://github.com/denamiel/mirivue-arch/releases/download/repository/`

Cette publication est un catalogue Pacman, pas une version des applications.
Elle contient les deux paquets signés, les archives sources correspondantes,
les bases `mirivue.db` et `mirivue.files` signées, la clé publique, son empreinte
et un manifeste signé indiquant les SHA des sources et des fichiers.
Les paquets sont mis en ligne avant le catalogue qui les référence.
Les anciens paquets et archives ne sont pas supprimés automatiquement.

Une régression de version, un paquet inattendu ou un changement de clé non
préparé fait échouer la publication. La rotation d'une clé demande une procédure
séparée : une nouvelle clé n'est jamais silencieusement imposée aux utilisateurs.

## Mise en service par le propriétaire

La configuration initiale a déjà été effectuée. [CONFIGURATION.md](CONFIGURATION.md)
décrit son fonctionnement et sa maintenance ; les utilisateurs n'ont pas à
recréer de clé ni à configurer GitHub. La clé privée et sa phrase secrète
ne doivent jamais être envoyées dans la conversation ou enregistrées dans Git.
Les scripts de configuration sont à lancer sur l'ordinateur du propriétaire.

## Installation sur Arch / CachyOS x86_64

Cette configuration se fait une seule fois sur l'ordinateur Arch/CachyOS.
Aucun compte GitHub ou AUR et aucune clé privée ne sont nécessaires.

1. Télécharger la [clé publique](https://github.com/denamiel/mirivue-arch/releases/download/repository/mirivue-key.asc)
   et afficher son empreinte :

   ```bash
   curl -fL https://github.com/denamiel/mirivue-arch/releases/download/repository/mirivue-key.asc -o /tmp/mirivue-key.asc
   gpg --show-keys --fingerprint /tmp/mirivue-key.asc
   ```

2. Comparer l'empreinte complète à celle confirmée par le propriétaire :

   ```text
   F22D CDD1 DF8D 9947 3E00 B8A3 7795 95DA 37BF E3E0
   ```

   Ne pas considérer une empreinte téléchargée avec la clé comme une preuve
   indépendante d'identité. En cas de différence, ne pas accorder la confiance.

3. Si elle correspond, importer puis approuver la clé :

   ```bash
   sudo pacman-key --add /tmp/mirivue-key.asc
   sudo pacman-key --lsign-key F22DCDD1DF8D99473E00B8A3779595DA37BFE3E0
   ```

4. Ajouter à la fin de `/etc/pacman.conf`, sans retirer les dépôts existants :

```ini
[mirivue]
SigLevel = Required DatabaseRequired
Server = https://github.com/denamiel/mirivue-arch/releases/download/repository
```

Puis installer l'édition voulue avec une mise à jour complète :

```bash
sudo pacman -Syu mirivue-gnome
# Ou : sudo pacman -Syu mirivue-kde
```

Pour installer les deux éditions : `sudo pacman -Syu mirivue-gnome mirivue-kde`.
Ne pas ajouter deux fois la section `[mirivue]` et ne pas utiliser `--overwrite`
pour masquer un conflit avec une ancienne installation ; vérifier sa provenance.

Les éditions peuvent coexister. Les mises à jour suivantes utilisent
`sudo pacman -Syu`. Ce dépôt fournit actuellement des versions bêta.
Il ne fournit pas de paquets pour Fedora ni pour ARM. COPR reste le circuit Fedora.

## Portée des vérifications

Les installations, signatures et dépendances sont testées dans un Arch Linux
à jour. Une session réelle GNOME/Plasma et l'ensemble des configurations
CachyOS ne sont pas reproduits par ces contrôles. Aucun fichier personnel
n'est utilisé dans les tests.

Les scripts de ce dépôt sont sous GPL-3.0-or-later ; les licences des applications
et de leurs composants restent celles publiées dans leurs sources et paquets.

## Références officielles

- https://man.archlinux.org/man/repo-add.8.en
- https://man.archlinux.org/man/pacman-key.8.en
- https://man.archlinux.org/man/pacman.conf.5.en
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
