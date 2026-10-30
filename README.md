# Mirivue — dépôt Pacman pour Arch Linux et CachyOS

**État : préparation et validation. La publication est désactivée tant que le
propriétaire n'a pas configuré sa clé et la variable `PUBLISH_ENABLED=true`.**
Ne pas ajouter ce dépôt à Pacman avant la première publication réussie.

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

Les deux paquets sont construits sans privilèges avec leurs recettes amont et
leurs contrôles `makepkg`. Une révision `pkgrel` propre au dépôt augmente lors
d'une reconstruction de la même version ; une nouvelle version repart de 1.
Une étape séparée vérifie les signatures et installe réellement les deux éditions
avec Pacman dans un conteneur Arch jetable. Les catalogues altérés ou non signés
et les paquets altérés doivent être refusés.

Les validations utilisent une clé éphémère de test, jamais publiée et supprimée
ensuite. Le job de publication dispose seul de la vraie clé et de l'autorisation
d'écriture des publications. Il est réservé à `main`, après tous les contrôles,
et n'est jamais exécuté pour une pull request.

Une fois activée, la recherche de nouvelles versions validées a lieu chaque heure.
Un lancement manuel est également possible depuis Actions. Sans changement,
le dépôt n'est pas reconstruit ; l'option `force_rebuild` permet au mainteneur
une reconstruction explicite avec nouvelle révision.

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

Voir [CONFIGURATION.md](CONFIGURATION.md). La clé privée et sa phrase secrète
ne doivent jamais être envoyées dans la conversation ou enregistrées dans Git.
Les scripts de configuration sont à lancer sur l'ordinateur du propriétaire.

## Installation sur Arch / CachyOS x86_64 — après activation

1. Télécharger `mirivue-key.asc` et afficher son empreinte avec
   `gpg --show-keys --fingerprint mirivue-key.asc`.
2. Vérifier cette empreinte complète auprès du propriétaire avant de lui accorder
   confiance. Ne pas considérer une empreinte téléchargée avec la clé comme une
   preuve indépendante de son identité.
3. Importer puis approuver cette clé avec `sudo pacman-key --add mirivue-key.asc`
   et `sudo pacman-key --lsign-key EMPREINTE_COMPLETE_VERIFIEE`.
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
