# AuditPulse on Oracle Cloud (Always Free)

One free server runs everything that used to be on Railway:

| Container  | What it is                                      | Public address (HTTPS)                           |
|------------|-------------------------------------------------|--------------------------------------------------|
| auditpulse | AuditPulse API + background worker (Celery)     | `https://auditpulse-api-<ip-with-dashes>.sslip.io`    |
| access     | Access portal API                               | `https://auditpulse-access-<ip-with-dashes>.sslip.io` |
| redis      | Queue for the worker (internal only)            | –                                                |
| caddy      | HTTPS with free Let's Encrypt certificates      | ports 80 / 443                                   |

Frontends stay on Vercel and the database stays on Supabase (both free).

## Stay free
* Use only **Always Free eligible** shapes: `VM.Standard.A1.Flex` (Arm) up to
  **2 OCPU / 12 GB** in total, boot volume ≤ 200 GB.
* Do **not** upgrade the account to Pay As You Go.
* Oracle may reclaim an Always Free server that stays idle for a long time —
  use it at least weekly.

## 1. Create the server (Oracle console)
1. Compute → Instances → **Create instance**.
2. Image: **Canonical Ubuntu 24.04** (or 22.04). Shape: **Ampere VM.Standard.A1.Flex**, 2 OCPU, 12 GB.
   If it says "Out of capacity", try another availability domain or try again later.
3. Networking: create a new VCN with a **public subnet**, assign a **public IPv4**.
4. SSH keys: upload the public key `oracle-secrets/auditpulse_oracle.pub`.
5. Create. Note the **public IP**.
6. Networking → the subnet's **Security list** → add ingress rules:
   source `0.0.0.0/0`, TCP, destination ports **80** and **443**.

## 2. Settings files
Fill `auditpulse.env` and `access.env` from `*.env.example` with the values
from Railway (Variables → Raw Editor). Keep them out of git.

## 3. Install
```bash
ssh -i oracle-secrets/auditpulse_oracle ubuntu@<public-ip> 'sudo mkdir -p /opt/auditpulse/env && sudo chown -R ubuntu /opt/auditpulse'
scp -i oracle-secrets/auditpulse_oracle auditpulse.env access.env ubuntu@<public-ip>:/opt/auditpulse/env/
scp -i oracle-secrets/auditpulse_oracle AuditPulse-main/deploy/oracle/setup.sh ubuntu@<public-ip>:~
ssh -i oracle-secrets/auditpulse_oracle ubuntu@<public-ip> 'bash setup.sh'
```
The first build takes 10–15 minutes (Chromium). It prints both HTTPS addresses.

## 4. Point the frontends at the new server
* **AuditPulse (Vercel)** → Settings → Environment Variables → `BACKEND_API_URL`
  = `https://auditpulse-api-<ip>.sslip.io` → Redeploy.
* **Access portal** → `js/config.js` → `API_BASE`
  = `https://auditpulse-access-<ip>.sslip.io/api` → push (Vercel redeploys).
* `access.env` → `PORTAL_BASE_URL` = the Access address above.

## Updating after a push
```bash
ssh -i oracle-secrets/auditpulse_oracle ubuntu@<public-ip> 'bash setup.sh'
```

## Useful commands (on the server)
```bash
cd /opt/auditpulse/AuditPulse/deploy/oracle
sudo docker compose ps                 # status
sudo docker compose logs -f auditpulse # API + worker logs
sudo docker compose restart auditpulse
```

## Moving to a paid host later
The same Dockerfile and start command work on Railway (`backend/railway.json`)
— copy the two `.env` files' values into the new host's variables.
