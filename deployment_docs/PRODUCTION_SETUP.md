# Production Setup Guide — EC2 Self-Hosted Stack

This guide walks through deploying the agent to a single EC2 t3.medium instance in Mumbai (ap-south-1).

## Prerequisites

- EC2 instance: **t3.medium** (4GB RAM, 2 vCPU, ₹3,270/mo)
- OS: **Ubuntu 24.04 LTS** or Amazon Linux 2
- SSH access
- AWS account (for S3 backups)
- .env configured with all credentials

## Phase 1: EC2 Setup (30 min)

### 1.1 Launch EC2 Instance

```bash
# Via AWS Console:
# - AMI: Ubuntu 24.04 LTS
# - Instance: t3.medium (ap-south-1 = Mumbai)
# - Storage: 30 GB gp3 (EBS)
# - Security Group: Allow SSH (22), HTTP (80), HTTPS (443)
# - Key Pair: Download and save

# Or via AWS CLI:
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.medium \
  --region ap-south-1 \
  --key-name your-key-pair \
  --security-groups agent-sg
```

### 1.2 Connect to Instance

```bash
ssh -i your-key-pair.pem ubuntu@<PUBLIC_IP>
```

### 1.3 Update System

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin git curl wget
sudo usermod -aG docker ubuntu
newgrp docker
```

### 1.4 Verify Docker

```bash
docker --version
docker run hello-world
```

## Phase 2: Clone & Configure (15 min)

### 2.1 Clone Repository

```bash
cd ~
git clone https://github.com/your-org/real-estate-agent.git
cd real-estate-agent
```

### 2.2 Set Up Environment

```bash
# Copy example and fill in credentials
cp .env.example .env

# Edit with your values
nano .env
```

**Required in .env:**
```
LIVEKIT_URL=wss://real-estate-agent-dadarhp7.livekit.cloud
LIVEKIT_API_KEY=APIQkaN...
LIVEKIT_API_SECRET=AH0kwBM...

DB_HOST=postgres
DB_PORT=5432
DB_NAME=agent_db
DB_USER=agent_user
DB_PASSWORD=<STRONG_PASSWORD>

DEEPGRAM_API_KEY=d2ea55b3...
GEMINI_API_KEY=AQ.Ab8RN...
SMALLEST_API_KEY=sk_2f68d1...
N8N_WEBHOOK_URL=http://localhost:5678/webhook/agent
VOBIZ_SIP_TRUNK_ID=ST_XUdu...
VOBIZ_SIP_DOMAIN=833eba91.sip.vobiz.ai

AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BACKUP_BUCKET=agent-db-backups
```

### 2.3 Create S3 Bucket for Backups

```bash
aws s3 mb s3://agent-db-backups --region ap-south-1
aws s3api put-bucket-versioning \
  --bucket agent-db-backups \
  --versioning-configuration Status=Enabled
```

## Phase 3: Deploy Stack (10 min)

### 3.1 Start Services

```bash
cd ~/real-estate-agent

# Start all services (Postgres, Agent, n8n)
docker-compose -f docker-compose.prod.yml up -d

# Verify
docker-compose -f docker-compose.prod.yml ps
```

Expected output:
```
NAME              STATUS
agent_postgres    Up 10s (healthy)
agent_livekit     Up 8s
agent_n8n         Up 5s
agent_nginx       Up 3s
```

### 3.2 Initialize Database

```bash
# Run migrations
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db -f /migrations/002_postgres_production_schema.sql

# Verify
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db -c "\dt"
```

### 3.3 Check Agent Logs

```bash
docker-compose -f docker-compose.prod.yml logs -f agent
```

Wait for:
```
✓ Postgres pool connected (postgres:5432/agent_db)
✓ LiveKit connected: wss://real-estate-agent-...
🚀 FIRST_TIME_INBOUND | Room: agent-...
```

## Phase 4: Set Up Backups (5 min)

### 4.1 Make Backup Script Executable

```bash
chmod +x scripts/backup_db.sh
```

### 4.2 Schedule Cron Job

```bash
# Edit crontab
crontab -e

# Add this line (runs every Sunday at 2 AM)
0 2 * * 0  /home/ubuntu/real-estate-agent/scripts/backup_db.sh

# Verify
crontab -l
```

### 4.3 Test Backup Manually

```bash
/home/ubuntu/real-estate-agent/scripts/backup_db.sh
cat /var/backups/agent_db/backup.log
```

Expected:
```
[2026-07-09 14:30:00] Starting database backup...
[2026-07-09 14:30:01] ✓ Backup created: /var/backups/agent_db/agent_db_backup_20260709_143000.sql.gz (2.1M)
[2026-07-09 14:30:05] ✓ S3 upload successful
[2026-07-09 14:30:05] ✓ Backup integrity verified
```

## Phase 5: Monitoring & Maintenance

### 5.1 View Logs

```bash
# Real-time agent logs
docker-compose -f docker-compose.prod.yml logs -f agent

# Last 100 lines
docker-compose -f docker-compose.prod.yml logs --tail=100 agent

# Specific service
docker-compose -f docker-compose.prod.yml logs -f postgres
docker-compose -f docker-compose.prod.yml logs -f n8n
```

### 5.2 Database Access

```bash
# Connect directly
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U agent_user -d agent_db

# Example queries
SELECT COUNT(*) FROM calls;
SELECT * FROM customers LIMIT 5;
SELECT * FROM calls WHERE created_at > now() - interval '24 hours';
```

### 5.3 Backup Verification

```bash
# List S3 backups
aws s3 ls s3://agent-db-backups/agent_db/ --recursive

# Download a backup
aws s3 cp s3://agent-db-backups/agent_db/agent_db_backup_20260709_143000.sql.gz .

# Restore from backup (emergency only!)
gunzip < agent_db_backup_20260709_143000.sql.gz | \
  docker-compose -f docker-compose.prod.yml exec -T postgres \
  psql -U agent_user -d agent_db
```

### 5.4 Monitor Disk Space

```bash
# Check disk usage
df -h

# Check Docker volumes
docker system df

# Clean up old backups (if disk full)
find /var/backups/agent_db -name "*.sql.gz" -mtime +7 -delete
```

## Phase 6: SSL/HTTPS Setup (Optional but Recommended)

### 6.1 Install Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 6.2 Get Certificate

```bash
sudo certbot certonly --standalone -d yourdomain.com
```

### 6.3 Update Nginx Config

```bash
# Copy SSL paths to docker-compose.prod.yml
# Then restart nginx

docker-compose -f docker-compose.prod.yml restart nginx
```

## Phase 7: Auto-Restart on Reboot

### 7.1 Enable Docker Service

```bash
sudo systemctl enable docker
```

### 7.2 Create SystemD Service (Optional)

```bash
sudo tee /etc/systemd/system/agent.service > /dev/null <<EOF
[Unit]
Description=Real Estate Agent Stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=/home/ubuntu/real-estate-agent
ExecStart=/usr/bin/docker-compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker-compose -f docker-compose.prod.yml down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable agent.service
sudo systemctl start agent.service
```

## Troubleshooting

### Agent won't connect to Postgres

```bash
# Check Postgres is running
docker-compose -f docker-compose.prod.yml exec postgres psql -U agent_user -c "SELECT 1"

# Check environment variables
docker-compose -f docker-compose.prod.yml exec agent env | grep DB_

# Check logs
docker-compose -f docker-compose.prod.yml logs agent | tail -20
```

### High memory usage

```bash
# Check memory per container
docker stats

# If over 3.5 GB, consider upgrading to t3.large
```

### Backup fails

```bash
# Check S3 permissions
aws s3 ls s3://agent-db-backups/

# Check backup script
bash -x /home/ubuntu/real-estate-agent/scripts/backup_db.sh

# Check cron logs
grep CRON /var/log/syslog | tail -20
```

### Can't access n8n (port 5678)

```bash
# Verify n8n is running
docker-compose -f docker-compose.prod.yml ps n8n

# Access via SSH tunnel
ssh -i key.pem -L 5678:localhost:5678 ubuntu@<PUBLIC_IP>
# Then visit http://localhost:5678
```

## Cost Verification

After deployment, verify costs match estimates:

```bash
# EC2 instance type (should be t3.medium)
aws ec2 describe-instances --region ap-south-1 \
  --query 'Reservations[].Instances[].{Type:InstanceType,State:State.Name}'

# S3 bucket size
aws s3 ls s3://agent-db-backups/ --recursive --summarize

# Expected monthly cost:
# EC2 t3.medium: ₹3,270
# S3 storage: ~₹50
# Total fixed: ₹3,320 + provider usage
```

## Going Live with a Client

Once deployed and tested:

1. Update `.env` with client's unique credentials
2. Create separate S3 bucket if multi-tenant: `agent-db-backups-client1`
3. Run backups test
4. Set up monitoring/alerts (CloudWatch, DataDog, etc.)
5. Document client's on-call escalation path
6. Schedule monthly backup verification

---

**Success! Your production stack is live. Enjoy ₹1,040/month savings vs. Supabase Pro.**
