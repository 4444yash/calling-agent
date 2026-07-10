# Calling Agent Documentation

Production-ready AI calling agent for outbound calls with post-call webhook integration.

---

## Quick Start

### Prerequisites
- Python 3.8+
- LiveKit Agents framework
- Supabase account (optional, for customer data enrichment)
- Deepgram API key (STT)
- Gemini API key (LLM)
- Smallest AI API key (TTS)

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run agent
lk agent start
```

### Configuration
All configuration is in `.env`:
- `DEEPGRAM_API_KEY` - Speech-to-text (Hindi)
- `GEMINI_API_KEY` - LLM (response generation)
- `SMALLEST_API_KEY` - Text-to-speech (Hindi)
- `SUPABASE_REST_URL` - Customer data lookup
- `N8N_WEBHOOK_URL` - Post-call data webhook

---

## Architecture

### Core Components
- **LiveKit Agents**: Real-time call handling
- **Deepgram Nova-3**: Hindi speech recognition
- **Gemini 3.1 Flash Lite**: Response generation
- **Smallest AI Lightning**: Hindi text-to-speech
- **Supabase**: Customer database (optional)
- **n8n**: Post-call workflow automation (optional)

### Call Flow
1. Incoming call connects to LiveKit room
2. Agent transcribes customer speech (Deepgram)
3. Agent looks up customer in Supabase (optional enrichment)
4. Agent generates response (Gemini LLM)
5. Agent speaks response (Smallest AI TTS)
6. On disconnect: Post-call data sent to n8n webhook
7. n8n stores data in Supabase and triggers follow-ups

---

## Production Fixes Applied

### Fix #1: HTTP Client Cleanup ✅
Gracefully closes HTTP connections on process exit (prevents port exhaustion after 2-3 weeks).

### Fix #2: Metadata Enrichment Timeout ✅
Never waits more than 2 seconds for customer lookup (prevents 10s silence if DB is slow).

### Fix #3: Track Background Tasks ✅
Tracks all post-call webhooks and ensures they complete before process exit (prevents data loss).

### Fix #4: Cap Retry Delays ✅
Limits exponential backoff to max 3 seconds total (prevents 7-10s hangs in voice calls).

---

## Deployment

### Local Testing
```bash
lk agent start
# Make test calls
# Monitor logs: tail -f agent_debug.log
```

### AWS Deployment
```bash
git push origin <branch>
# Deploy to EC2 in ap-south-1
# Restart agent
```

---

## Monitoring

### Key Metrics
- Call duration
- STT latency (Deepgram response time)
- LLM latency (Gemini response time)
- TTS latency (Smallest AI response time)
- Post-call webhook delivery time

### Logs
- **Normal operation**: "📞 Room disconnected."
- **Metadata timeout**: "⏱️ Metadata enrichment timed out"
- **Task tracking**: "Post-call webhook queued (pending: X)"
- **Webhook completed**: "✓ Post-call webhook completed"

---

## Troubleshooting

### Issue: 10s silence at call start
**Cause**: Customer lookup taking >2s  
**Solution**: Fix #2 handles this with 2s timeout

### Issue: Calls disconnecting after weeks
**Cause**: TCP port exhaustion  
**Solution**: Fix #1 handles cleanup on shutdown

### Issue: Post-call data missing in n8n
**Cause**: Webhook task lost if process crashed  
**Solution**: Fix #3 tracks tasks and ensures delivery

### Issue: Long delays between customer speech and agent response
**Cause**: Retry backoff exceeding 3s  
**Solution**: Fix #4 caps retry delays

---

## Support

For issues or questions:
1. Check logs: `agent_debug.log`
2. Verify `.env` configuration
3. Test API keys individually
4. Check network connectivity to services

---

## Files

```
src/
├── agent.py              # Main calling agent (4 production fixes applied)
├── prompts.py            # Scenario-specific prompts
└── utils/
    ├── supabase_client.py  # Safe database client
    ├── resilience.py       # Retry + circuit breaker logic
    └── validation.py       # Input validation

migrations/
└── 001_whatsapp_schema.sql  # Database schema (for reference)

docs/
└── README.md             # This file
```

---

**Status**: ✅ Production ready with all resilience fixes applied.
