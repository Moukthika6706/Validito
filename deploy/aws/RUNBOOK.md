# Deploying Validito on AWS (EC2 + Docker Compose)

One Ubuntu EC2 instance runs the whole stack (MySQL, Redis, API, Celery worker, nginx +
React) with `docker compose`. Cost: a `t3.medium` is roughly $0.04/hour (~$30/month); stop
the instance when not demoing.

## 1. AWS account and IAM user (one-time)

1. Sign in at https://console.aws.amazon.com. Do day-to-day work as an **IAM user**, not the
   root account: IAM → Users → *Create user* → name `validito-admin`, tick *Provide user access
   to the AWS Management Console* → attach policy `AdministratorAccess` (fine for a personal
   learning account) → create, note the sign-in URL, sign out of root and back in as that user.
2. Pick a region near you (top-right), e.g. `ap-south-1` (Mumbai) or `eu-west-2` (London), and
   stay in it for every step below.

## 2. Key pair

EC2 → *Key pairs* → *Create key pair* → name `validito-key`, type RSA, format `.pem` → the
browser downloads `validito-key.pem`. Keep it; it is the only way to SSH in.

## 3. Security group (the firewall)

EC2 → *Security groups* → *Create*: name `validito-sg`. Inbound rules:

| Type | Port | Source | Why |
|---|---|---|---|
| SSH | 22 | *My IP* | your terminal only |
| HTTP | 80 | Anywhere-IPv4 (0.0.0.0/0) | the app |

Nothing else. MySQL/Redis/API are not published by the production compose file.

## 4. Launch the instance

EC2 → *Instances* → *Launch instances*:

- Name `validito`
- AMI: **Ubuntu Server 24.04 LTS** (64-bit x86)
- Instance type: **t3.medium** (2 vCPU, 4 GB; `t3.small` is too small to build the OCR image)
- Key pair: `validito-key`
- Network: select existing security group `validito-sg`; *Auto-assign public IP*: Enable
- Storage: **30 GiB gp3** (the backend image with PyTorch + EasyOCR is ~2 GB; builds need headroom)
- Advanced details → *User data*: paste the contents of `deploy/aws/ec2-user-data.sh`
- Launch. Wait until *Status checks* says 2/2 passed (~2 minutes), then another ~2 minutes for
  the bootstrap script to finish (`/var/log/validito-bootstrap.log` on the box).

Copy the instance's **Public IPv4 DNS** (looks like `ec2-13-233-1-2.ap-south-1.compute.amazonaws.com`).

## 5. Connect

From your machine (Git Bash / PowerShell), in the folder holding the `.pem`:

```bash
chmod 400 validito-key.pem          # Git Bash / macOS / Linux; skip on PowerShell
ssh -i validito-key.pem ubuntu@<PUBLIC-DNS>
```

On the box, confirm the bootstrap finished:

```bash
tail -3 /var/log/validito-bootstrap.log     # ends with "validito bootstrap complete"
docker --version && docker compose version
ls /opt/validito
```

If `docker` says permission denied, log out and back in (the `docker` group applies on a new login).

## 6. Configure

```bash
cd /opt/validito
cp .env.production.example .env
nano .env
```

Set at least:

- `SECRET_KEY` → paste the output of `openssl rand -hex 32`
- `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` → anything strong
- `FRONTEND_BASE_URL` and `CORS_ORIGINS` → `http://<PUBLIC-DNS>` (no trailing slash)

Save (Ctrl+O, Enter, Ctrl+X).

## 7. Build and start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The first build takes 10–20 minutes (PyTorch, spaCy model, EasyOCR models). Watch it:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
```

You are done when the api log shows `Application startup complete` after the seed lines
(`isda_irs_clean.pdf -> auto_approved`, ...). Check health:

```bash
curl -s http://localhost/health
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Open `http://<PUBLIC-DNS>` in a browser. Demo logins are in the project README.

## 8. A link that survives restarts (Elastic IP)

A stopped/started instance gets a new public IP. EC2 → *Elastic IPs* → *Allocate* → select it →
*Actions → Associate* → your instance. Update `FRONTEND_BASE_URL`/`CORS_ORIGINS` in `.env` to the
new address and run the `up -d` command again (no rebuild needed). An Elastic IP is free while
attached to a running instance.

## 9. Updating after a git push

```bash
cd /opt/validito && git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Migrations run automatically on API start (`alembic upgrade head` in the entrypoint).

## 10. Useful commands

```bash
# status / logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker
# restart one service
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
# stop everything (data volumes are kept)
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
# wipe the database and start over
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
```

## Next steps (not needed for a demo)

- A domain + HTTPS: point an A record at the Elastic IP and put Caddy in front of nginx for
  automatic Let's Encrypt certificates.
- Managed services: move MySQL to RDS and Redis to ElastiCache, then run API and worker on
  ECS Fargate; the images and env vars stay the same.
- Backups: `docker compose exec mysql mysqldump -u root -p validito > backup.sql`, or RDS snapshots.
