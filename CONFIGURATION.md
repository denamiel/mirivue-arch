# Activer la signature et la publication

Les fichiers sont préparés ; aucun paquet de production n'est publié avant
configuration. Ces opérations appartiennent au propriétaire du dépôt.

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
- la variable `PUBLISH_ENABLED=true`, qui autorise les publications suivantes.

Il désactive d'abord la publication pendant la configuration, vérifie le compte
GitHub utilisé et déclenche le premier workflow. Aucun secret n'est écrit dans
le dépôt ni affiché dans le terminal. Conserver la clé et la phrase hors ligne.

Une configuration manuelle est également possible dans Settings > Secrets and
variables > Actions, avec les mêmes noms. Activer la variable `PUBLISH_ENABLED`
seulement après avoir ajouté les deux secrets et l'empreinte complète.

## 4. Vérifier la première publication

Ouvrir l'onglet Actions. Les étapes de construction des deux applications,
l'installation des paquets signés et la publication doivent réussir.
La publication `repository` contient alors notamment `mirivue.db`, sa signature,
les deux paquets et leurs signatures, `mirivue-key.asc`, `fingerprint.txt`
et `manifest.json` signé. Comparer l'empreinte publiée à la clé locale.

Ne pas configurer les ordinateurs clients avant cette réussite. Les commandes
client figurent dans README.md. L'empreinte complète vérifiée est indispensable.

## Suspension et renouvellement

Mettre `PUBLISH_ENABLED=false` suspend les nouvelles publications, sans retirer
le dépôt existant. Une clé expirée ou incorrecte provoque un échec ; aucune clé
non reconnue ou clé de test n'est utilisée en remplacement. Prévoir son
renouvellement avant l'échéance. Ne pas remplacer la clé de confiance sans une
procédure explicite de transition pour les utilisateurs.
