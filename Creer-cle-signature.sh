#!/usr/bin/env bash
# Run by the owner on their own computer. Never prints or uploads a private key.
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
umask 077
command -v gpg >/dev/null || { echo 'Installez GnuPG avant de continuer.' >&2; exit 1; }
signing_dir="${XDG_STATE_HOME:-$HOME/.local/state}/mirivue-arch/signature"
if [[ -e "$signing_dir" ]]; then
  echo "Le dossier existe déjà : $signing_dir. Aucun fichier n'a été remplacé." >&2
  exit 1
fi
mkdir -p "$signing_dir/gnupg"
chmod 700 "$signing_dir" "$signing_dir/gnupg"
export GNUPGHOME="$signing_dir/gnupg"
if [[ -t 0 ]]; then export GPG_TTY="$(tty)"; fi
echo 'Choisissez une phrase secrète non vide dans la fenêtre GnuPG.'
gpg --quick-generate-key 'Mirivue Arch packages' ed25519 sign 2y
fingerprint="$(gpg --with-colons --fingerprint --list-secret-keys | awk -F: '$1 == "fpr" {print $10; exit}')"
test -n "$fingerprint"
gpg --armor --export "$fingerprint" > "$signing_dir/mirivue-key.asc"
gpg --armor --export-secret-keys "$fingerprint" > "$signing_dir/private-key.asc"
printf '%s\n' "$fingerprint" > "$signing_dir/fingerprint.txt"
echo "Clé et export privé chiffré conservés dans : $signing_dir"
echo "Empreinte publique : $fingerprint"
echo 'Ne transmettez jamais private-key.asc ni votre phrase secrète dans la conversation.'
echo 'Les commandes de configuration GitHub figurent dans CONFIGURATION.md.'
