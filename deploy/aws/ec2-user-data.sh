#!/bin/bash
# EC2 "user data" bootstrap for Ubuntu 24.04: installs Docker + Compose, adds swap (the OCR
# image build is memory-hungry), and clones Validito into /opt/validito.
# Paste this into Advanced details -> User data when launching the instance.
set -euxo pipefail
exec > >(tee /var/log/validito-bootstrap.log) 2>&1

# 1. Docker Engine + Compose plugin from Docker's own repository
apt-get update
apt-get install -y ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# 2. 4 GB swap so the backend image builds comfortably on a 4 GB instance
if ! swapon --show | grep -q swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 3. The code
if [ ! -d /opt/validito ]; then
  git clone https://github.com/Moukthika6706/Validito.git /opt/validito
  chown -R ubuntu:ubuntu /opt/validito
fi

echo "validito bootstrap complete"
