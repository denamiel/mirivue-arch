#!/usr/bin/env bash
# User-operated setup. Secrets go directly to GitHub, never into Git or chat.
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
command -v gh >/dev/null || { echo 'Installez GitHub CLI (gh).' >&2; exit 1; }
gh auth status >/dev/null
account="$(gh api user --jq .login)"
[[ "$account" == denamiel ]] || { echo 'Sélectionnez le compte GitHub denamiel dans gh.' >&2; exit 1; }
signing_dir="${XDG_STATE_HOME:-$HOME/.local/state}/mirivue-arch/signature"
test -f "$signing_dir/private-key.asc"
fingerprint="$(cat "$signing_dir/fingerprint.txt")"
[[ "$fingerprint" =~ ^[A-F0-9]{40}$ ]] || { echo 'Empreinte de signature invalide.' >&2; exit 1; }
repository='denamiel/mirivue-arch'
gh variable set PUBLISH_ENABLED --repo "$repository" --body false
gh secret set SIGNING_PRIVATE_KEY --repo "$repository" --env publication-pacman < "$signing_dir/private-key.asc"
read -r -s -p 'Phrase secrète de la clé GnuPG (saisie masquée) : ' signing_password
printf '\n'
[[ -n "$signing_password" ]] || { echo 'Une phrase secrète non vide est requise.' >&2; exit 1; }
printf '%s' "$signing_password" | gh secret set SIGNING_PASSPHRASE --repo "$repository" --env publication-pacman
unset signing_password
gh variable set SIGNING_FINGERPRINT --repo "$repository" --body "$fingerprint"
# Main-only publication replaces per-release manual approvals.
if ! gh api "repos/$repository/environments/publication-pacman" \
        --jq '[.protection_rules[] | select(.type == "required_reviewers")] | length' 2>/dev/null | grep -qx 0; then
    echo 'Publication laissée désactivée : configurez publication-pacman sans reviewers.' >&2
    exit 1
fi
if ! gh api "repos/$repository/branches/main" --jq .protected | grep -qx true; then
    echo 'Publication laissée désactivée : protégez main avec PR et validation obligatoire.' >&2
    exit 1
fi
gh variable set PUBLISH_ENABLED --repo "$repository" --body true
echo 'Publications automatiques des nouvelles versions validées activées.'
echo 'Aucun workflow n’a été lancé par ce script. Suivi :'
echo "https://github.com/$repository/actions"
