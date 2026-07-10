# Cost Optimization Summary

## Problem
For a single client with 2000 calls/month, fixed infrastructure costs (database + hosting) were consuming 50-60% of potential revenue.

## Solution
Implemented a two-tier deployment strategy:
1. **Free Tier for Trials** — Show clients full capability before commitment
2. **Production EC2 Stack** — Minimal fixed costs when client pays

---

## Tier 1: FREE Trial Stack

**For:** Pilots, demos, clients with <1000 calls/month

```
┌─ LiveKit Cloud Build (FREE)
│  └─ 1,000 agent-session minutes/month
│
├─ Supabase Free (FREE)
│  └─ 500 MB database, auto-pause risk
│
├─ Providers: Your own keys (BYOK)
│  └─ Deepgram, Gemini, Smallest AI
│
└─ Total Fixed Cost: ₹0

Usage cost (~300 calls): ₹2,500-3,000/month
```

**Setup:** No server needed. Deploy agent to LiveKit Cloud free tier, point to Supabase Free project.

**Limitations:**
- 1,000 minute ceiling (hard stop)
- Supabase auto-pauses after 7 days idle
- No backups

**Mitigation:**
- Keep-alive cron to prevent pause
- Weekly manual backup via `pg_dump`
- Clear trial limits in contract

---

## Tier 2: PRODUCTION EC2 Stack (Recommended)

**For:** Live revenue clients, 2000+ calls/month

### Architecture

```
EC2 t3.medium (Mumbai)
├─ Agent (src/agent.py)
├─ Postgres database
├─ n8n webhook receiver
└─ Cron backups → S3

S3 backups (4 weekly dumps)
└─ 28-day retention
```

### Monthly Cost Breakdown

| Item | Cost | Notes |
|------|------|-------|
| EC2 t3.medium | ₹3,270 | ap-south-1, 4GB RAM |
| S3 backups | ₹50 | 4 backups × 2.5 MB |
| **Fixed subtotal** | **₹3,320** | One-time infrastructure |
| Deepgram STT (6000 min) | ₹1,800 | Your API key, ₹0.30/min |
| Gemini LLM (tokens) | ₹800 | Your API key |
| Smallest AI TTS (6000 min) | ₹1,500 | Your API key, ₹0.25/min |
| Vobiz SIP | [your rate] | Your existing trunk |
| **Total with usage** | **~₹7,420** | Scales linearly with calls |

**Per-minute cost:** ~₹1.24/min (agent + providers, not including SIP)

### Savings vs. Previous Stack

| Component | Before (Supabase Pro) | After (EC2 Self-Postgres) | Savings |
|-----------|---------------------|------------------------|---------|
| Database | ₹2,090 | ₹0 (included in EC2) | **₹2,090/mo** |
| Hosting | ₹3,270 (EC2) | ₹3,270 (EC2) | $0 |
| Backups | Included | ₹50 | +₹50 |
| **Monthly fixed** | **₹5,360** | **₹3,320** | **₹2,040/mo** |
| **Annual fixed** | **₹64,320** | **₹39,840** | **₹24,480/year** |

---

## Migration Path

### Timeline

| Phase | When | Action | Cost |
|-------|------|--------|------|
| **Prototype** | NOW | Use free LiveKit + Supabase Free | ₹0 |
| **Pilot** | 1-2 weeks | Demo with client on free tier | ₹0 |
| **Production** | After contract | Spin up EC2, migrate to Postgres | ₹3,320/mo |

### Step-by-Step

**Phase 1: Trial (Nothing to do)**
- Agent already points to LiveKit Cloud free tier
- Supabase account is free
- Just test with real calls

**Phase 2: Launch Production**
1. Spin up EC2 t3.medium in Mumbai (₹3,270/mo)
2. Deploy Docker stack: `docker-compose -f docker-compose.prod.yml up -d`
3. Initialize Postgres schema
4. Migrate any test data
5. Reconfigure agent to point to local Postgres
6. Set up weekly backup cron
7. Test end-to-end inbound + outbound calls
8. Go live with client

---

## Multi-Tenant Scaling

As you add more clients, the fixed ₹3,320 amortizes across all of them.

| Clients | Fixed cost | Per-client fixed | Scaling |
|---------|-----------|-----------------|---------|
| 1 | ₹3,320 | ₹3,320 | n/a |
| 3 | ₹3,320 | ₹1,107 | Use `tenant_id` in DB |
| 5 | ₹3,320 | ₹664 | Add more clients ⚙️ |
| 10 | ₹5,400 | ₹540 | Upgrade to t3.large |

**Database growth:** Your schema easily fits 10+ clients (still <500 MB total). No DB upgrade needed until 50+ clients.

---

## Files Created / Updated

### New Files
```
DEPLOYMENT_STRATEGY.md ..................... High-level overview
PRODUCTION_SETUP.md ........................ Step-by-step EC2 guide
COST_OPTIMIZATION_SUMMARY.md ............... This file
migrations/002_postgres_production_schema.sql  Postgres schema
src/utils/postgres_client.py .............. Postgres driver
scripts/backup_db.sh ....................... Weekly backup cron
docker-compose.prod.yml ................... Full stack (Postgres+Agent+n8n)
```

### Updated Files
```
.env.example ......................... Documented both setups
Dockerfile .......................... Updated for Postgres
```

---

## Key Files to Use

### For Trial (FREE)
- Keep current `.env` pointing to Supabase
- Use free LiveKit workspace
- No changes needed

### For Production
- Copy `.env` → `.env.prod`
- Update DB credentials to local Postgres
- Run: `docker-compose -f docker-compose.prod.yml up -d`
- Run backup script: `chmod +x scripts/backup_db.sh`
- Add to crontab

---

## Quality Assurance

**Switching from Supabase Free → EC2 Postgres loses NO functionality:**
- Same agent logic ✓
- Same providers (Deepgram, Gemini, Smallest AI) ✓
- Same concurrency limits (4-6 calls on t3.medium) ✓
- Same backup strategy (weekly exports) ✓

**Gains:**
- No auto-pause ✓
- Reliable backups (managed by you) ✓
- Lower fixed cost ✓
- Better scaling story ✓

---

## Estimated Timeline

| Task | Time | Owner |
|------|------|-------|
| Test on free tier | 1 week | Your team |
| Get client commitment | 2 weeks | Sales |
| Spin up EC2 | 15 min | You |
| Deploy Docker stack | 10 min | You |
| Initialize database | 5 min | You |
| Set up backups | 5 min | You |
| Test end-to-end | 1-2 hours | You |
| Go live | <24 hours | You |

---

## Next Steps

1. ✅ **Test agent on free LiveKit** (no setup needed)
2. ✅ **Create trial contract** (mention 1000-min limit)
3. **When client signs:** Provision EC2 + follow `PRODUCTION_SETUP.md`
4. **Monitor for 1 month** (verify costs, backups, uptime)
5. **Add more clients** (same EC2 instance, new tenant_id)

---

## Support

**Questions?**
- Database issues → Check `PRODUCTION_SETUP.md` troubleshooting
- Cost questions → See above cost breakdown
- Multi-tenant setup → Use `tenant_id` column isolation + RLS

**Emergency:** If Postgres corrupts, restore from S3 backup via:
```bash
aws s3 cp s3://agent-db-backups/latest.sql.gz - | gunzip | psql -U agent_user -d agent_db
```

---

**Total Savings: ₹2,040/month fixed, ₹24,480/year. Scale to 10 clients = 90% cost reduction per client.**
