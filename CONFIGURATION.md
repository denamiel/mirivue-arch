# Configuration de la signature et maintenance

La configuration initiale et la première publication signée ont réussi :
https://github.com/denamiel/mirivue-arch/actions/runs/41141962504

Ce guide concerne le propriétaire et une éventuelle nouvelle installation du
circuit de publication. Les utilisateurs Arch/CachyOS suivent uniquement
[README.md](README.md) ; ils n'ont pas à créer de clé ou de secret GitHub.
Ne pas recréer ni remplacer la clé existante pour une mise à jour ordinaire.
Les étapes ci-dessous décrivent la configuration initiale, pas une opération
à répéter à chaque version.

## 1. Préparer son ordinateur

Sur Fedora : `sudo dnf install git gnupg2 gh`.
Sur Arch/CachyOS : `sudo pacman -Syu --needed git gnupg github-cli`.

Télécharger ou cloner `https://github.com/denamiel/mirivue-arch`, puis ouvrir
un terminal dans son dossier. Les deux scripts suivants se lancent avec `bash`,
y compris lorsque le terminal habituel utilise fish. Ne pas les lancer avec sudo.

## 2. Créer une clé dédiée

```bash
bash Creer-cle-signature.sh
```

GnuPG demande une phrase secrète : choisir une phrase non vide et la conserver.
Le script crée une clé de signature Ed25519 valable deux ans, sans adresse
personnelle dans son identité publique. Il utilise un trousseau dédié, sans
modifier les clés personnelles existantes.

La clé, un export privé chiffré et l'empreinte publique restent dans
`$XDG_STATE_HOME/mirivue-arch/signature` (ou `~/.local/state/mirivue-arch/signature`).
Un dossier déjà existant n'est jamais écrasé. Sauvegarder ce dossier hors ligne.
Ne partager dans la conversation que l'empreinte publique si nécessaire,
jamais `private-key.asc` ni la phrase secrète.

## 3. Connexion GitHub CLI et configuration

Si GitHub CLI n'est pas connecté au compte `denamiel`, exécuter `gh auth login`
et suivre sa procédure dans le navigateur. Pour ce dépôt public, l'accès doit
permettre la gestion des secrets, variables et déclenchements Actions.

```bash
bash Configurer-publication-GitHub.sh
```

Le script envoie directement à GitHub, au dépôt `denamiel/mirivue-arch` :

- le secret `SIGNING_PRIVATE_KEY` depuis le fichier local ;
- le secret `SIGNING_PASSPHRASE`, demandé en saisie masquée ;
- la variable publique `SIGNING_FINGERPRINT` ;
- la variable `PUBLISH_ENABLED=true`, qui rend les publications possibles.

La publication est automatique pour les nouvelles versions validées. Créer
l’environnement `publication-pacman` avec *Deployment branches* limité à `main`,
sans *Required reviewers* ni délai. Protéger `main` avec PR obligatoire et le
contrôle **Validation du dépôt signé**, sans suppression, réécriture ou bypass.
Le modèle de ruleset est fourni dans le dépôt KDE :
`packaging/protection-mirivue-arch.json`.

Le script désactive la publication pendant la configuration. Les deux secrets
sont enregistrés dans l’environnement `publication-pacman` ; la variable publique
`SIGNING_FINGERPRINT` reste dans les variables du dépôt. Il ne réactive
`PUBLISH_ENABLED` que si l’environnement et la protection de `main` sont prêts.
Cela autorise les prochaines publications automatiques ; aucun workflow n’est
lancé par le script lui-même. Une configuration manuelle peut utiliser Settings
> Environments > publication-pacman > Environment secrets. Ne pas recréer la
clé existante pour une simple mise à jour.

## 4. Vérifier la première publication

Ouvrir l'onglet Actions. Les étapes de construction des deux applications,
l'installation des paquets signés et la publication doivent réussir.
La publication `repository` contient alors notamment `mirivue.db`, sa signature,
les deux paquets et leurs signatures, `mirivue-key.asc`, `fingerprint.txt`
et `manifest.json` signé. Comparer l'empreinte publiée à la clé locale.

Ne pas configurer les ordinateurs clients avant cette réussite. Les commandes
client figurent dans README.md. L'empreinte complète vérifiée est indispensable.

## Contrôler un passage planifié sans nouvelle version

Après chaque modification du workflow, vérifier en lecture seule le dernier
passage planifié, sans jamais lancer une vraie publication pour tester :

```bash
gh run list --repo denamiel/mirivue-arch --workflow repository.yml --event schedule --limit 1 \
  --json databaseId --jq '.[0].databaseId' \
  | xargs -I{} gh run view {} --repo denamiel/mirivue-arch --json jobs \
      --jq '.jobs[] | select(.name | startswith("Publier")) | "\(.name) : \(.conclusion)"'
```

Sans hausse de version validée, résultat attendu : `skipped`, et le fichier `manifest.json` de la publication
`repository` inchangé.

## Suspension et renouvellement

Mettre `PUBLISH_ENABLED=false` suspend les nouvelles publications, sans retirer
le dépôt existant. Une clé expirée ou incorrecte provoque un échec ; aucune clé
non reconnue ou clé de test n'est utilisée en remplacement. Prévoir son
renouvellement avant l'échéance. Ne pas remplacer la clé de confiance sans une
procédure explicite de transition pour les utilisateurs.
