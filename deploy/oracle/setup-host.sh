#!/usr/bin/env bash
# One-time host preparation for the Oracle Always Free VM (Ubuntu 24.04).
#
# Run after SSHing into the VM:
#   curl -fsSL https://raw.githubusercontent.com/nithyaa021/civiclens/main/deploy/oracle/setup-host.sh | sudo bash
# or, after cloning:
#   sudo ./setup-host.sh
#
# It installs Docker Engine + Compose v2, enables a host firewall for SSH/HTTP/
# HTTPS, creates the deploy directory, configures a small swap file and installs
# a nightly Mongo backup cron entry.  It does not copy secrets or start the app.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root (sudo ./setup-host.sh)." >&2
  exit 1
fi

TARGET_USER="${SUDO_USER:-ubuntu}"
if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "User $TARGET_USER does not exist; set TARGET_USER to the SSH user." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  docker.io \
  docker-compose-v2 \
  fail2ban \
  git \
  openssl \
  ufw \
  unattended-upgrades

systemctl enable --now docker

# Allow the deploy user to run Docker without sudo.  A new SSH session picks
# this up; the current shell may still need `newgrp docker`.
usermod -aG docker "$TARGET_USER"

# Only Caddy publishes host ports.  Mongo/Redis/Qdrant/API stay private.
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

install -d -o "$TARGET_USER" -g "$TARGET_USER" /opt/civiclens
install -d -o "$TARGET_USER" -g "$TARGET_USER" /opt/civiclens/backups

# A small swap file protects against a transient NLLB/CLIP spike.  The VM has
# 24 GB of RAM, so this is a safety net rather than the working set.
if ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  if ! grep -q '^/swapfile ' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
fi

cat >/etc/sysctl.d/99-civiclens.conf <<'EOF'
vm.swappiness=10
EOF
sysctl --system >/dev/null

# Security updates only; this does not reboot the VM.
dpkg-reconfigure -f noninteractive unattended-upgrades || true

# Nightly logical backup, retained for seven days by backup.sh.
cat >/etc/cron.d/civiclens-backup <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 2 * * * $TARGET_USER /opt/civiclens/deploy/oracle/backup.sh >> /var/log/civiclens-backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/civiclens-backup

echo
echo "Host preparation complete."
echo "Log out and back in (or run 'newgrp docker') so $TARGET_USER can use Docker."
echo "Then clone the repository into /opt/civiclens and follow deploy/oracle/README.md."
