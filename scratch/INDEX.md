# Scratch Directory - Testing & Debugging Tools

Complete collection of test scripts and utilities for testing and debugging the calling agent.

---

## 📽️ Recording Tools (NEW)

Complete suite for downloading and analyzing LiveKit call recordings.

### Scripts
- **`download_livekit_recordings.py`** - Download recordings from LiveKit Cloud
- **`analyze_call_quality.py`** - Analyze audio quality metrics
- **`playback_recordings.py`** - Play, convert, and manage recordings

### Documentation
- **`RECORDING_TOOLS_README.md`** - Full documentation (600+ lines)
- **`QUICK_START_RECORDINGS.md`** - Quick start guide (250+ lines)
- **`RECORDING_TOOLS_SUMMARY.md`** - Feature summary

### Getting Started
```bash
# Download 5 recent recordings
python download_livekit_recordings.py --recent 5

# Analyze quality
python analyze_call_quality.py recordings/room/file.webm

# Play recording
python playback_recordings.py --play recording.webm
```

**More info**: See `QUICK_START_RECORDINGS.md` for 5-minute setup

---

## 🧪 Testing Scripts

### Core Tests
- **`test_raw_smallest.py`** - Test Smallest AI TTS API directly
- **`test_livekit_tts.py`** - Test LiveKit TTS integration
- **`test_db_lookup.py`** - Test database lookup functionality
- **`test_round_robin.py`** - Test round-robin load balancing

### Advanced Tests
- **`test_nc_crash.py`** - Test noise cancellation crash scenarios
- **`test_nc_real_room.py`** - Test NC in real room conditions
- **`test_tts_latency.py`** - Measure TTS latency
- **`test_twirp_endpoints.py`** - Test TWIRP endpoints

### Utilities
- **`check_trunks.py`** - Check SIP trunk configuration
- **`trigger_outbound.py`** - Trigger outbound calls
- **`trigger_n8n_outbound.py`** - Trigger outbound via n8n

---

## 📖 Quick Reference

| Task | File | Command |
|------|------|---------|
| Download recordings | `download_livekit_recordings.py` | `--recent 5` |
| Analyze audio quality | `analyze_call_quality.py` | `recording.webm` |
| Play recording | `playback_recordings.py` | `--play file.webm` |
| Convert to MP3 | `playback_recordings.py` | `--convert file.webm` |
| Test TTS | `test_livekit_tts.py` | Run directly |
| Test DB | `test_db_lookup.py` | Run directly |
| Check trunks | `check_trunks.py` | Run directly |

---

## 🚀 Common Workflows

### Pre-Deployment Testing
```bash
# 1. Download recent calls
python download_livekit_recordings.py --recent 3

# 2. Analyze each
python analyze_call_quality.py recordings/**/*.webm

# 3. Listen to best and worst
python playback_recordings.py --play best.webm
python playback_recordings.py --play worst.webm

# 4. If quality < 80, debug before deploying
```

### Production Monitoring
```bash
# Weekly quality check
python download_livekit_recordings.py --recent 10
for f in recordings/**/*.webm; do
    python analyze_call_quality.py "$f"
done
# Track quality scores over time
```

### Issue Debugging
```bash
# 1. Find call in logs
grep "customer_phone" ../src/agent.py

# 2. Download recording from that time
python download_livekit_recordings.py --download room_name

# 3. Analyze and listen
python analyze_call_quality.py recordings/room_name/*.webm
python playback_recordings.py --play problem_recording.webm

# 4. Compare with logs
cat ../agent_debug.log | grep "Room: room_name"
```

---

## 📦 Dependencies

### Required
- Python 3.8+
- httpx
- python-dotenv

### Optional (for analysis)
- ffmpeg (audio analysis, MP3 conversion)
- VLC/mpv (audio playback)

### Installation
```bash
# Core
pip install httpx python-dotenv

# Full (macOS)
brew install ffmpeg vlc

# Full (Ubuntu)
sudo apt-get install ffmpeg vlc
```

---

## 🎯 When to Use Each Tool

### Recording Tools (Download & Analyze)
**Use when**: Testing agent audio quality, debugging call issues, monitoring production

**Example**: 
```bash
# Call quality complaint from customer
python download_livekit_recordings.py --download problem_room
python analyze_call_quality.py recordings/problem_room/*.webm
python playback_recordings.py --play problem_recording.webm
```

### TTS Tests
**Use when**: Testing text-to-speech latency, voice quality, language support

**Example**:
```bash
# Check TTS is working
python test_livekit_tts.py
# Or measure latency
python test_tts_latency.py
```

### Database Tests
**Use when**: Testing customer lookup, data enrichment, metadata queries

**Example**:
```bash
python test_db_lookup.py
```

---

## 📊 Recording Tools Details

### download_livekit_recordings.py
**Purpose**: Retrieve call recordings from LiveKit Cloud

**Features**:
- List all recordings
- Download recent recordings (customizable count)
- Download by room name or ID
- Batch operations with progress
- Auto-organize by date/room
- Generate metadata JSON

**Output**: `recordings/room_name/*.webm` + `recordings_metadata.json`

### analyze_call_quality.py
**Purpose**: Analyze audio quality of recordings

**Features**:
- Extract audio metrics
- Detect quality issues
- Generate quality score (0-100)
- Provide recommendations
- Export analysis as JSON

**Output**: Quality report + `file_analysis.json`

**Scores**:
- 90+: Excellent ✅
- 70-89: Good ✓
- 50-69: Fair ⚠️
- <50: Poor ❌

### playback_recordings.py
**Purpose**: Manage recording library

**Features**:
- List recordings
- Play with system player
- Convert WebM → MP3
- Export metadata
- Delete recordings
- Storage usage summary

**Output**: Plays audio or converts files

---

## 🔧 Configuration

### Environment Variables (.env)
```
# Required for recording downloads
LIVEKIT_URL=wss://your-livekit-url
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret

# Optional (other components)
DEEPGRAM_API_KEY=...
GEMINI_API_KEY=...
SMALLEST_API_KEY=...
SUPABASE_REST_URL=...
N8N_WEBHOOK_URL=...
```

---

## 📁 File Organization

```
scratch/
├── Recording Tools (NEW)
│   ├── download_livekit_recordings.py
│   ├── analyze_call_quality.py
│   ├── playback_recordings.py
│   ├── RECORDING_TOOLS_README.md
│   ├── QUICK_START_RECORDINGS.md
│   └── RECORDING_TOOLS_SUMMARY.md
│
├── Testing Scripts
│   ├── test_raw_smallest.py
│   ├── test_livekit_tts.py
│   ├── test_db_lookup.py
│   ├── test_round_robin.py
│   ├── test_nc_crash.py
│   ├── test_nc_real_room.py
│   ├── test_tts_latency.py
│   └── test_twirp_endpoints.py
│
├── Utilities
│   ├── check_trunks.py
│   ├── trigger_outbound.py
│   ├── trigger_n8n_outbound.py
│   └── INDEX.md (this file)

recordings/ (auto-created)
├── room_name_1/
│   ├── recording_xyz.webm
│   ├── recording_xyz.mp3
│   └── recording_xyz.json
└── recordings_metadata.json
```

---

## 🚨 Troubleshooting

### Recording Download Issues
```
Problem: "No recordings found"
Solution: Check LIVEKIT_URL, LIVEKIT_API_KEY in .env

Problem: "Connection refused"
Solution: Verify LiveKit server is running
```

### Analysis Issues
```
Problem: "ffprobe not found"
Solution: Install ffmpeg (brew install ffmpeg)

Problem: Quality score < 50
Solution: Check audio quality in recording, verify sample rate
```

### Playback Issues
```
Problem: "No audio player found"
Solution: Install VLC (brew install vlc)

Problem: Cannot open file
Solution: Use file manager to verify file exists
```

---

## 📈 Metrics to Track

### Audio Quality
- Sample rate: Should be 24000 Hz
- Channels: Should be 2 (stereo)
- Bitrate: Should be 128+ kbps
- Quality score: Should be 80+

### Call Metrics (from logs)
- STT latency: Should be <1s
- LLM latency: Should be <2s
- TTS latency: Should be <1s
- Total silence (customer speaks to agent speaks): Should be <3s

### Combine metrics
- Recording quality + log latencies = complete picture
- If quality poor AND latencies high = network issue
- If quality good BUT latencies high = component slow

---

## ✨ Best Practices

1. **Weekly Downloads**: Download 5-10 recent calls every week
2. **Analyze All**: Run quality analysis on all downloads
3. **Track Trends**: Keep quality scores to track improvement
4. **Archive**: Convert old recordings to MP3, delete WebM
5. **Share**: Convert to MP3 when sharing with team
6. **Debug**: Always listen to recording when quality < 80

---

## 🔗 Related Documentation

- **Recording Tools Full Guide**: `RECORDING_TOOLS_README.md`
- **Quick Start**: `QUICK_START_RECORDINGS.md`
- **Feature Summary**: `RECORDING_TOOLS_SUMMARY.md`
- **Agent Logs**: `../agent_debug.log`
- **Production Fixes**: `../PRODUCTION_FIXES.md`

---

## 🎬 Next Steps

1. **Setup**: Install dependencies
   ```bash
   pip install httpx python-dotenv
   brew install ffmpeg
   ```

2. **Verify**: Check .env configuration
   ```bash
   cat ../.env | grep LIVEKIT
   ```

3. **Test**: Download and analyze recordings
   ```bash
   python download_livekit_recordings.py --list
   python download_livekit_recordings.py --recent 3
   python analyze_call_quality.py recordings/**/*.webm
   ```

4. **Monitor**: Set up weekly analysis
   ```bash
   # Create a cron job or scheduled task
   # Run every Monday morning:
   # python download_livekit_recordings.py --recent 10
   ```

---

**Status**: ✅ All tools ready for use

**Last Updated**: July 9, 2026

**For Issues**: Check QUICK_START_RECORDINGS.md troubleshooting section
