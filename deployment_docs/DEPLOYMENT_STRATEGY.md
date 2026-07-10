# Deployment Strategy & Pricing Guide

## Current Status (July 2026)

The real-estate-agent project uses:
- **Agent runtime:** LiveKit Agents (Python)
- **Providers:** Deepgram (STT), Google Gemini (LLM), Smallest AI (TTS)
- **Database:** Supabase (REST API)
- **Telephony:** Vobiz SIP trunk
- **Workflows:** n8n for post-call automation

---

## Two Deployment Strategies

### 1. FREE TIER TRIAL STACK (for client demos)

**Perfect for:** Pilots, trials, proof-of-concept (~1000 calls/month)

```
┌─ LiveKit Cloud Build (FREE)
│  ├─ 1,000 agent-session minutes/month
│  ├─ 1,000 SIP minutes/month (Vobiz)
│  ├─ 5 concurrent sessions
│  ├─ 1 agent deployment
│  └─ Inference credits (not used - bring your own providers)
│
├─ Supabase Free (FREE)
│  ├─ 500 MB database
│  ├─ Auto-pause after 7 days idle
│  ├─ 5 GB egress
│  └─ No backups
│
├─ Providers (bring your own keys)
│  ├─ Deepgram STT API key
│  ├─ Google Gemini API key
│  ├─ Smallest AI TTS API key
│  └─ Vobiz SIP credentials
│
└─ n8n (optional, self-hosted or local for webhooks)

TOTAL FIXED COST: ₹0
USAGE COST (~1000 calls @ 3min avg): ~₹2,500-3,000/mo in provider charges
LIMIT: ~330 calls/month or 7-day pause risk
```

**Advantages:**
- Literally zero platform cost
- Show client full functionality
- Easy to disable/pause between demos

**Limitations & Risks:**
- 1,000 minute ceiling (hard stop at ~330 calls)
- Supabase auto-pauses after 7 days without activity (can break a demo)
- No backups on Supabase Free
- Only 1 client per LiveKit account

**Mitigation for trials:**
1. Use free tier for 1-2 week active trial only
2. Add a keep-alive cron to prevent Supabase auto-pause (ping DB every 2 days)
3. Document the trial limits upfront ("try it for 2 weeks free")

---

### 2. PRODUCTION STACK (when client pays)

**For:** Live revenue-generating client, 2000 calls/month (~6,000 agent-minutes)

#### Option A: EC2 Self-Hosted (RECOMMENDED - Lowest Cost)

```
┌─ EC2 t3.medium (ap-south-1 Mumbai)
│  ├─ Agent runtime (src/agent.py)
│  ├─ Postgres database (replaces Supabase)
│  ├─ n8n workflow engine
│  └─ Cron: weekly pg_dump backups to S3
│
├─ S3 backup storage
│  ├─ 4 weekly pg_dumps (~50 MB each = ₹50/mo)
│  └─ 28-day retention
│
├─ LiveKit Cloud (SIP connectivity only, agent self-hosted)
│  ├─ Third-party SIP minutes (via Vobiz trunk)
│  ├─ Used only for SIP routing, NOT agent hosting
│  └─ ~5,000 min included on Build tier
│
├─ Providers (same as trial)
│  ├─ Deepgram, Gemini, Smallest AI
│  └─ Your API keys
│
└─ Vobiz SIP (your current trunk)

MONTHLY COSTS:
├─ EC2 t3.medium ................... ₹3,270
├─ S3 backups ...................... ₹50
├─ LiveKit SIP minutes (if overage) . $0-5
├─ Deepgram (6000 min @ ₹0.30/min) . ₹1,800
├─ Gemini LLM (est. tokens) ........ ₹800
├─ Smallest AI TTS (6000 min) ...... ₹1,500
└─ Vobiz SIP (your trunk cost) .... [client pays]

TOTAL FIXED: ₹3,320/mo
TOTAL WITH PROVIDERS: ~₹7,420/mo
LIMIT: 4-6 concurrent, unlimited calls/month
```

**Advantages:**
- Lowest fixed cost (₹3,320/mo)
- Full control, no vendor lock-in
- Scales to 10+ concurrent on same instance
- One infrastructure bill, simple to manage
- Backups are your responsibility but cheap (₹50/mo)

**Your responsibilities:**
- Postgres updates/patching
- SSH access and basic Linux ops
- Weekly backup verification

---

#### Option B: LiveKit Cloud Hosted (Maximum Convenience)

```
┌─ LiveKit Cloud Ship tier ($50/mo)
│  ├─ Agent runs on LiveKit infrastructure
│  ├─ 5,000 agent-session minutes included
│  ├─ 5,000 SIP minutes (Vobiz)
│  ├─ 20 concurrent sessions (auto-scaled)
│  ├─ 2 agent deployments (multi-client ready)
│  └─ Deploy with: lk agent deploy
│
├─ Supabase Pro (₹2,090/mo)
│  ├─ 8 GB database
│  ├─ No auto-pause
│  ├─ Daily backups + PITR
│  └─ Email support
│
├─ Providers (same)
│  └─ Deepgram, Gemini, Smallest AI
│
└─ Vobiz SIP

MONTHLY COSTS:
├─ LiveKit Ship .................... $50 (~₹4,200)
├─ Supabase Pro .................... ₹2,090
├─ Provider usage (~4,100/mo) ...... ₹4,100
└─ Vobiz SIP ...................... [client pays]

TOTAL FIXED: ₹6,290/mo
TOTAL WITH PROVIDERS: ~₹10,390/mo
LIMIT: 20 concurrent, ~500K calls/month possible
```

**Advantages:**
- Zero server management
- Auto-scaling built-in
- Multi-client ready (2 deployments on Ship)
- Supabase Pro includes backups

**Disadvantages:**
- ₹2,970/mo more than EC2 self-hosted
- Slightly higher latency (agent runs far from you)

---

## RECOMMENDATION

| Scenario | Stack | Cost | When |
|----------|-------|------|------|
| **Trial/Demo** | LiveKit Build + Supabase Free | ₹0 | Show client before they pay |
| **Single paying client** | **EC2 t3.medium + self-Postgres** | **₹3,320 fixed** | **When they commit to contract** |
| **2-3 clients** | EC2 t3.medium + self-Postgres | ₹3,320 (amortized) | Scale by adding clients |
| **Multi-tenant SaaS** | LiveKit Ship + Supabase Pro | ₹6,290 fixed | When you need 5+ deployments |

---

## Migration Path

1. **NOW:** Trial on free LiveKit + Supabase Free
2. **When client signs contract:** Move to EC2 self-hosted stack
3. **When you have 3+ clients:** Consider upgrading to LiveKit Ship for easier scaling

---

## Setup Checklist

### Phase 1: Trial Stack (Quick Setup)

- [ ] Create LiveKit Cloud account (free tier)
- [ ] Point agent to free LiveKit workspace
- [ ] Keep current Supabase FREE project
- [ ] Test with Deepgram/Gemini/Smallest AI keys
- [ ] Document 1000-minute trial limit in contracts

### Phase 2: Production Stack (EC2 Migration)

- [ ] Provision EC2 t3.medium (ap-south-1)
- [ ] Install Postgres on EC2
- [ ] Migrate Supabase schema to Postgres
- [ ] Update agent to connect to local Postgres
- [ ] Set up weekly pg_dump → S3 backup cron
- [ ] Deploy agent with Docker
- [ ] Run n8n on same EC2
- [ ] Test end-to-end (inbound + outbound calls)

---

## Key URLs & Credentials

| Service | URL | Status |
|---------|-----|--------|
| LiveKit Cloud | https://cloud.livekit.io | Free tier active |
| Supabase | https://app.supabase.com | Free project active |
| AWS S3 (backups) | aws.amazon.com | Set up during Phase 2 |
| Vobiz SIP | (in .env) | Active |

---

## Cost Savings Achieved

| Item | Before (Supabase Pro) | After (EC2 self-Postgres) | Savings |
|------|---------------------|------------------------|---------|
| Monthly fixed | ₹4,410 | ₹3,320 | **₹1,090/mo (25%)** |
| Backup cost | ₹0 (Supabase included) | ₹50 | +₹50 |
| Net monthly | ₹4,410 | ₹3,370 | **₹1,040/mo savings** |
| Annual | ₹52,920 | ₹40,440 | **₹12,480 savings/year** |

---

## Questions & Troubleshooting

**Q: What if agent crashes on EC2?**
A: Set up systemd service to auto-restart. Add monitoring with CloudWatch.

**Q: How long do backups take?**
A: pg_dump of your tiny DB takes <1 second. S3 upload negligible.

**Q: Can I use free tier forever?**
A: LiveKit Build is 1,000 min/month hard ceiling. Once client exceeds ~330 calls/month, upgrade to Ship.

**Q: What if I want to add another client?**
A: Same EC2 can handle 5+ clients with different tenant_id isolation. No infrastructure change needed.

---

## Files to Update

1. `src/agent.py` — Update Supabase REST calls to Postgres
2. `Dockerfile` — Add postgres-client, adjust paths
3. `.env` — Point to local Postgres instead of Supabase
4. `.env.example` — Document both connection types
5. `backup.sh` (new) — Weekly pg_dump script
6. `docker-compose.yml` (new) — Agent + Postgres + n8n stack

