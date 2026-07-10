# Quick Start: Production Deployment

**TL;DR** — Deploy the agent to your own EC2 instance in 45 minutes and save ₹2,040/month.

---

## 1. Provision EC2 (5 min)

```bash
# Via AWS Console or CLI
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \  # Ubuntu 24.04 in ap-south-1
  --instance-type t3.medium \
  --region ap-south-1 \
  --security-groups agent-sg

# Note the Public IP
```

---

## 2. Connect & Setup Docker (10 min)

```bash
ssh -i key.pem ubuntu@<PUBLIC_IP>

# One-liner installation
sudo apt update && apt install -y docker.io docker-compose-plugin git && sudo usermod -aG docker ubuntu && newgrp docker

# Test
docker run hello-world
```

---

## 3. Deploy Stack (10 min)

```bash
# Clone
git clone https://github.com/your-org/real-estate-agent.git && cd real-estate-agent

# Configure
cp .env.example .env
# Edit .env with your secrets (use nano or vim)
nano .env

# Launch
docker-compose -f docker-compose.prod.yml up -d

# Check
docker-compose -f docker-compose.prod.yml ps
```

**Expected output:**
```
CONTAINER ID   STATUS              NAMES
xxxxx          Up 10s (healthy)    agent_postgres
xxxxx          Up 8s               agent_livekit
xxxxx          Up 5s               agent_n8n
```

---

## 4. Initialize Database (5 min)

```bash
# Run migrations
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db -f /migrations/002_postgres_production_schema.sql

# Verify
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db -c "\dt"
```

---

## 5. Setup Backups (5 min)

```bash
# Make backup script executable
chmod +x scripts/backup_db.sh

# Add to crontab (every Sunday 2 AM)
(crontab -l; echo "0 2 * * 0  $(pwd)/scripts/backup_db.sh") | crontab -

# Test
./scripts/backup_db.sh

# Verify backup in S3
aws s3 ls s3://agent-db-backups/
```

---

## 6. Test End-to-End (10 min)

```bash
# Check agent logs
docker-compose -f docker-compose.prod.yml logs -f agent

# Should see:
# ✓ Postgres pool connected (postgres:5432/agent_db)
# ✓ LiveKit connected: wss://real-estate-agent-...
# 🚀 FIRST_TIME_INBOUND | Room: agent-...

# Make a test call via Vobiz SIP or n8n

# Verify call logged
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db -c "SELECT COUNT(*) FROM calls; SELECT * FROM calls ORDER BY created_at DESC LIMIT 1;"
```

---

## 7. Go Live 🚀

```bash
# Add your real customer phone numbers
# Configure n8n workflows
# Test with real SIP calls
# Monitor logs
docker-compose -f docker-compose.prod.yml logs -f

# To stop
docker-compose -f docker-compose.prod.yml down

# To update
git pull
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

---

## Cost Recap

| Stack | Monthly | Annual |
|-------|---------|--------|
| **Old: Supabase Pro** | ₹5,360 | ₹64,320 |
| **New: EC2 Self-Postgres** | ₹3,320 | ₹39,840 |
| **Savings** | **₹2,040** | **₹24,480** |

Plus 0% quality loss. Same agent logic, same providers.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Agent won't connect to Postgres | `docker-compose exec postgres psql -U agent_user -c "SELECT 1"` |
| High memory usage | Check `docker stats` — if >3.5 GB, upgrade to t3.large |
| Backup fails | Check S3 permissions: `aws s3 ls s3://agent-db-backups/` |
| Can't SSH | Verify security group allows port 22 |
| Docker command not found | Restart bash: `newgrp docker` |

---

## Full Docs

- **Cost deep-dive:** `COST_OPTIMIZATION_SUMMARY.md`
- **Full setup guide:** `PRODUCTION_SETUP.md`
- **Complete checklist:** `SETUP_CHECKLIST.md`
- **Architecture overview:** `DEPLOYMENT_STRATEGY.md`

---

**You're live in 45 minutes. Enjoy the savings!** ✨
