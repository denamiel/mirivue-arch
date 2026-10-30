#!/usr/bin/env bash
# Run only in the disposable Arch CI container, never on the maintainer's PC.
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
repository_dir="$(realpath -- "$1")"
validation_dir="$(mktemp -d)"
trap 'rm -rf -- "$validation_dir"' EXIT
mkdir -p "$validation_dir/keyring" "$validation_dir/db" "$validation_dir/cache"
pacman-key --gpgdir "$validation_dir/keyring" --init
pacman-key --gpgdir "$validation_dir/keyring" --populate archlinux
pacman-key --gpgdir "$validation_dir/keyring" --add "$repository_dir/mirivue-key.asc"
pacman-key --gpgdir "$validation_dir/keyring" --lsign-key "$(cat "$repository_dir/fingerprint.txt")"
cp /etc/pacman.conf "$validation_dir/pacman.conf"
cat >> "$validation_dir/pacman.conf" <<EOF

[mirivue]
SigLevel = Required DatabaseRequired
Server = file://$repository_dir
EOF
# Real dependency resolution and coexistence installation, with signatures.
pacman --config "$validation_dir/pacman.conf" --gpgdir "$validation_dir/keyring" \
  --noconfirm -Syu mirivue-gnome mirivue-kde
mirivue-gnome --version
mirivue-kde --version
QT_QPA_PLATFORM=offscreen timeout 45 mirivue-kde --smoke-test
xvfb-run -a dbus-run-session -- timeout 45 mirivue-gnome --window-smoke-test
# Signature failures must never be accepted as a valid repository.
mkdir "$validation_dir/bad"
cp "$repository_dir/mirivue.db" "$validation_dir/bad/mirivue.db"
cp "$repository_dir/mirivue.db.sig" "$validation_dir/bad/mirivue.db.sig"
printf '\ntampered\n' >> "$validation_dir/bad/mirivue.db"
cat > "$validation_dir/bad.conf" <<EOF
[options]
Architecture = x86_64
SigLevel = Required DatabaseRequired
[mirivue]
Server = file://$validation_dir/bad
EOF
if pacman --config "$validation_dir/bad.conf" --dbpath "$validation_dir/db" \
   --cachedir "$validation_dir/cache" --gpgdir "$validation_dir/keyring" --noconfirm -Sy; then
  echo 'ERROR: pacman accepted a modified repository database' >&2
  exit 1
fi
cp "$repository_dir/mirivue.db" "$validation_dir/bad/mirivue.db"
rm -- "$validation_dir/bad/mirivue.db.sig"
rm -rf -- "$validation_dir/db/sync"
if pacman --config "$validation_dir/bad.conf" --dbpath "$validation_dir/db" \
   --cachedir "$validation_dir/cache" --gpgdir "$validation_dir/keyring" --noconfirm -Sy; then
  echo 'ERROR: pacman accepted an unsigned repository database' >&2
  exit 1
fi
package="$(find "$repository_dir" -maxdepth 1 -name '*.pkg.tar.zst' -print -quit)"
cp "$package" "$validation_dir/tampered.pkg.tar.zst"
printf '\ntampered\n' >> "$validation_dir/tampered.pkg.tar.zst"
if gpg --batch --verify "$package.sig" "$validation_dir/tampered.pkg.tar.zst"; then
  echo 'ERROR: a modified package passed signature verification' >&2
  exit 1
fi
