# Setup Checklist

## Current Status

✅ Documentation complete  
✅ Postgres driver created  
✅ Database schema prepared  
✅ Docker compose configured  
✅ Backup script ready  
✅ Environment templates updated  

---

## Phase 1: Trial Setup (For Demo Clients) — 5 min

### Before Demo
- [ ] Verify agent connects to free LiveKit Cloud workspace
- [ ] Confirm Supabase Free project is active
- [ ] Test one inbound call (3+ min) via Vobiz SIP
- [ ] Confirm call transcripts save to Supabase
- [ ] Check n8n receives post-call webhook

### During Trial
- [ ] Document 1,000-minute limit in contract
- [ ] Warn about 7-day auto-pause risk
- [ ] Ask client to make at least 1 call every 3 days

### After 2-Week Trial
- [ ] If client commits → Move to Phase 2
- [ ] If client declines → Disable LiveKit workspace, archive

---

## Phase 2: Production Deployment (When Client Pays) — 1-2 hours

### AWS Account Setup
- [ ] Create S3 bucket: `agent-db-backups`
- [ ] Create IAM user with S3 + EC2 permissions
- [ ] Save AWS credentials in .env

### EC2 Provisioning (15 min)
- [ ] Provision **t3.medium** in **ap-south-1** (Mumbai)
- [ ] Set security group to allow SSH (22), HTTP (80), HTTPS (443)
- [ ] Download key pair and save securely
- [ ] Note public IP address

### EC2 Configuration (10 min)
```bash
ssh -i key.pem ubuntu@<IP>
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker ubuntu
newgrp docker
docker --version  # Verify
```
- [ ] SSH access working
- [ ] Docker installed
- [ ] Docker hello-world works

### Code Deployment (10 min)
```bash
cd ~
git clone https://github.com/your-org/real-estate-agent.git
cd real-estate-agent
cp .env.example .env
nano .env  # Fill in credentials
```
- [ ] Repository cloned
- [ ] .env configured with all secrets
- [ ] LIVEKIT_URL correct
- [ ] DB credentials strong
- [ ] Provider API keys present

### Database Stack (10 min)
```bash
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml ps
```
- [ ] Postgres container running
- [ ] Agent container running  
- [ ] n8n container running
- [ ] All show "healthy" status

### Database Initialization (5 min)
```bash
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db -f /migrations/002_postgres_production_schema.sql
```
- [ ] Schema created (no errors)
- [ ] Tables created: agents, customers, properties, ad_clicks, calls

### Backup Setup (5 min)
```bash
chmod +x scripts/backup_db.sh
crontab -e
# Add: 0 2 * * 0  /path/to/scripts/backup_db.sh
./scripts/backup_db.sh  # Test manually
```
- [ ] Script is executable
- [ ] Cron job scheduled (Sunday 2 AM)
- [ ] First backup created in /var/backups/agent_db
- [ ] Backup uploaded to S3

### Testing (1-2 hours)

#### Inbound Call Test
```
1. Call Vobiz SIP trunk (or test via n8n webhook)
2. Verify agent answers in Hindi
3. Check call record in Postgres:
   docker-compose exec postgres psql -U agent_user -d agent_db \
   -c "SELECT * FROM calls ORDER BY created_at DESC LIMIT 1"
4. Verify post-call data in n8n logs
```
- [ ] Inbound call connects
- [ ] Agent responds naturally
- [ ] Call duration logged
- [ ] Transcript saved
- [ ] n8n webhook received

#### Outbound Call Test (via n8n)
```
1. Trigger outbound scenario from n8n
2. Verify agent calls customer
3. Check ad_click_outbound scenario runs
4. Verify call logged as "outbound"
```
- [ ] Outbound call triggers
- [ ] Agent uses correct scenario
- [ ] Direction recorded correctly

#### Database Test
```bash
# Verify data persists
docker-compose exec postgres psql -U agent_user -d agent_db <<EOF
SELECT COUNT(*) as call_count FROM calls;
SELECT DISTINCT scenario FROM calls;
SELECT * FROM customers LIMIT 3;
EOF
```
- [ ] Calls table has records
- [ ] All scenarios logged
- [ ] Customer data present

#### Backup Restoration Test (Critical!)
```bash
# Download latest backup
aws s3 cp s3://agent-db-backups/agent_db/ . --recursive

# Restore to test database
gunzip < agent_db_backup_*.sql.gz | \
  docker-compose exec -T postgres \
  psql -U agent_user -d test_db
```
- [ ] Backup file downloads
- [ ] Restore completes without errors
- [ ] Data integrity verified

#### Concurrent Call Test (4-5 calls)
```
1. Simulate 4-5 simultaneous calls via n8n
2. Monitor CPU/RAM:
   docker stats
3. Verify all calls handled without dropping
4. Check no errors in logs
```
- [ ] All 4-5 calls handled
- [ ] CPU <80%
- [ ] RAM <3.5 GB
- [ ] No dropped calls
- [ ] Logs clean (no errors)

### Monitoring Setup (Optional)
- [ ] CloudWatch alerts for CPU >80%
- [ ] Disk space alerts
- [ ] Email notifications on backup failure

### Client Handoff
- [ ] Confirm SIP credentials working end-to-end
- [ ] Show client call logs (via Postgres UI or dashboard)
- [ ] Document client's phone number(s)
- [ ] Set up monitoring/on-call escalation
- [ ] Document backup/restore procedure

---

## Phase 3: Month 1 (Monitoring)

### Weekly
- [ ] Check backup logs: `cat /var/backups/agent_db/backup.log`
- [ ] Verify S3 has 4 recent backups
- [ ] Monitor disk space: `df -h`

### Monthly
- [ ] Review EC2 bill (verify ₹3,270)
- [ ] Check database size: `du -h /var/lib/docker/volumes/postgres_data`
- [ ] Run cost optimization report
- [ ] Test backup restoration once (emergency drill)

### If Issues Arise
- [ ] Check logs: `docker-compose logs -f agent`
- [ ] Verify Postgres: `docker-compose exec postgres psql -U agent_user -c "SELECT 1"`
- [ ] Check disk space immediately
- [ ] Review PRODUCTION_SETUP.md troubleshooting section

---

## Phase 4: Scale to More Clients

### For Each New Client
- [ ] Add `tenant_id` column to calls/customers/properties tables
- [ ] Create new n8n workflow using tenant_id
- [ ] Create separate S3 backup bucket (or prefix)
- [ ] No new EC2 needed (same t3.medium)
- [ ] Update backup script for multi-tenant
- [ ] Repeat testing on same EC2

### When to Upgrade Infrastructure
- [ ] **CPU >80% sustained** → Upgrade to t3.large (₹5,400)
- [ ] **RAM >3.5 GB consistent** → Upgrade to t3.large
- [ ] **Database >500 MB** → Still fine, plan for t3.large when >2 GB
- [ ] **Concurrent calls >8** → Definitely upgrade to t3.large

---

## Cost Verification Checklist

✅ Trial (Free) = ₹0 fixed  
✅ Production (1 client) = ₹3,320 fixed/mo  
✅ At 3 clients = ₹1,107 per client  
✅ At 5 clients = ₹664 per client  

**Verify every month:**
```bash
# Check AWS bill
aws ce get-cost-and-usage --time-period Start=2026-07-01,End=2026-07-31 \
  --granularity MONTHLY --metrics "UnblendedCost" --group-by Type=DIMENSION,Key=SERVICE

# Check EC2 instance type
aws ec2 describe-instances --region ap-south-1 \
  --query 'Reservations[].Instances[].[InstanceType,State.Name]'

# Check S3 storage
aws s3 ls s3://agent-db-backups --recursive --summarize
```

---

## Emergency Procedures

### Database Corruption
```bash
# 1. Download latest backup from S3
aws s3 cp s3://agent-db-backups/latest.sql.gz .

# 2. Stop agent to prevent writes
docker-compose -f docker-compose.prod.yml stop agent

# 3. Restore backup
gunzip < latest.sql.gz | docker-compose exec -T postgres psql -U agent_user -d agent_db

# 4. Restart agent
docker-compose -f docker-compose.prod.yml up -d agent

# 5. Verify data integrity
docker-compose exec postgres psql -U agent_user -d agent_db -c "SELECT COUNT(*) FROM calls"
```
- [ ] Backup procedure documented
- [ ] Team trained on restore process
- [ ] Test restore monthly (not just in emergency)

### Disk Full
```bash
# Check what's using space
du -sh /var/lib/docker/volumes/*
docker system df

# Clean old backups
find /var/backups/agent_db -name "*.sql.gz" -mtime +14 -delete

# Restart Docker services
docker-compose -f docker-compose.prod.yml down
docker system prune -f
docker-compose -f docker-compose.prod.yml up -d
```

### Agent Won't Start
```bash
# Check logs
docker-compose logs agent | tail -50

# Verify Postgres is running
docker-compose exec postgres psql -U agent_user -c "SELECT 1"

# Verify environment variables
docker-compose config | grep DB_

# Restart
docker-compose down
docker-compose -f docker-compose.prod.yml up -d
```

---

## Sign-Off

- [ ] All documentation read and understood
- [ ] Trial client tested on free tier
- [ ] Production stack tested end-to-end
- [ ] Team trained on deployment
- [ ] Backups tested and verified
- [ ] Monitoring set up
- [ ] Emergency procedures documented
- [ ] Ready for revenue client launch ✅

---

**Estimated completion: 2-3 days (with testing)**

When you check all boxes above, you're production-ready. Go live! 🚀
