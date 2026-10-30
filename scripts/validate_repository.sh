#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
repository_dir="$(realpath -- "$1")"
validation_dir="$(mktemp -d)"
trap 'rm -rf -- "$validation_dir"' EXIT
mkdir -p "$validation_dir/keyring" "$validation_dir/db" "$validation_dir/cache"
pacman-key --gpgdir "$validation_dir/keyring" --init
pacman-key --gpgdir "$validation_dir/keyring" --add "$repository_dir/mirivue-key.asc"
pacman-key --gpgdir "$validation_dir/keyring" --lsign-key "$(cat "$repository_dir/fingerprint.txt")"
cat > "$validation_dir/pacman.conf" <<EOF
[options]
Architecture = x86_64
SigLevel = Required DatabaseRequired
[mirivue]
Server = file://$repository_dir
EOF
pacman --config "$validation_dir/pacman.conf" --dbpath "$validation_dir/db" \
  --cachedir "$validation_dir/cache" --gpgdir "$validation_dir/keyring" --noconfirm -Sy
pacman --config "$validation_dir/pacman.conf" --dbpath "$validation_dir/db" --gpgdir "$validation_dir/keyring" -Sl mirivue
for package in "$repository_dir/"*.pkg.tar.zst; do
  gpg --batch --verify "$package.sig" "$package"
done
