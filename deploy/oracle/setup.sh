#!/usr/bin/env bash
# ==============================================================================
# One-time setup of an Oracle Cloud Always Free Ubuntu server (Arm or x86).
# Run as the default "ubuntu" user:   bash setup.sh
# Re-running it is safe: it updates the code and restarts everything.
# Needs /opt/auditpulse/env/auditpulse.env and access.env to exist first.
# ==============================================================================
set -euo pipefail
ROOT=/opt/auditpulse
AP_REPO=${AP_REPO:-https://github.com/Jeevanks1998/AuditPulse.git}
AC_REPO=${AC_REPO:-https://github.com/Jeevanks1998/AuditPulse-Access.git}

echo "==> Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "==> Firewall: open 80/443 (Oracle Ubuntu images reject them by default)"
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -p tcp --dport $p -j ACCEPT
done
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent >/dev/null 2>&1 || true
sudo netfilter-persistent save >/dev/null 2>&1 || true

echo "==> Code"
sudo mkdir -p $ROOT/env && sudo chown -R "$USER":"$USER" $ROOT
for pair in "AuditPulse|$AP_REPO" "AuditPulse-Access|$AC_REPO"; do
  dir=${pair%%|*}; url=${pair#*|}
  if [ -d "$ROOT/$dir/.git" ]; then git -C "$ROOT/$dir" pull --ff-only; else git clone --depth 1 "$url" "$ROOT/$dir"; fi
done

for f in auditpulse.env access.env; do
  [ -s "$ROOT/env/$f" ] || { echo "Missing $ROOT/env/$f - copy it to the server first."; exit 1; }
done
chmod 600 $ROOT/env/*.env

echo "==> Host names"
IP=$(curl -fsS https://api.ipify.org || curl -fsS https://ifconfig.me)
DASHED=${IP//./-}
cat > $ROOT/AuditPulse/deploy/oracle/.env <<HOSTS
API_HOST=auditpulse-api-$DASHED.sslip.io
ACCESS_HOST=auditpulse-access-$DASHED.sslip.io
HOSTS
cat $ROOT/AuditPulse/deploy/oracle/.env

echo "==> Build and start (first build takes 10-15 minutes: Chromium)"
cd $ROOT/AuditPulse/deploy/oracle
sudo docker compose up -d --build
sudo docker compose ps
echo
echo "AuditPulse API:    https://auditpulse-api-$DASHED.sslip.io/health"
echo "Access portal API: https://auditpulse-access-$DASHED.sslip.io/api/health"
