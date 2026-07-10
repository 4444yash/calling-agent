# Quick Start: Download & Analyze Call Recordings

**Goal**: Download your call recordings from LiveKit, analyze audio quality, and understand how your agent is performing.

---

## 5-Minute Setup

### Step 1: Verify Environment
Ensure your `.env` has LiveKit credentials:
```bash
cat .env | grep LIVEKIT
# Should show:
# LIVEKIT_URL=wss://...
# LIVEKIT_API_KEY=...
# LIVEKIT_API_SECRET=...
```

### Step 2: Install Dependencies
```bash
# Core dependencies (already in requirements.txt)
pip install httpx python-dotenv

# Optional: ffmpeg for analysis and conversion
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

### Step 3: Download Recent Calls
```bash
cd scratch

# Download 5 most recent recordings
python download_livekit_recordings.py --recent 5

# List what was downloaded
python playback_recordings.py --list
```

**Output**:
```
recordings/
├── room_name_1/
│   └── recording_xyz_20260709_145530.webm (3.2 MB)
├── room_name_2/
│   └── recording_abc_20260709_143215.webm (2.8 MB)
└── recordings_metadata.json
```

---

## 10-Minute Analysis

### Step 4: Analyze Audio Quality
```bash
# Analyze one recording
python analyze_call_quality.py recordings/room_name_1/recording_xyz_20260709_145530.webm

# Output:
# ✅ Quality Score: 92/100 (Excellent)
# 🔊 Audio Metrics:
#    Sample Rate: 24000 Hz
#    Channels: 2
#    Bitrate: 192 kbps
```

### Step 5: Listen to Recording
```bash
# Play a recording
python playback_recordings.py --play recording_xyz_20260709_145530.webm

# Listen for:
# ✓ Agent greeting (clear speech)
# ✓ Customer response (audible)
# ✓ Natural conversation flow
# ✗ Audio cutting/popping
# ✗ Long silences between turns
```

---

## Understanding Results

### Quality Score Interpretation

| Score | Meaning | Action |
|-------|---------|--------|
| 90+ | Excellent | No action needed |
| 70-89 | Good | Monitor, document patterns |
| 50-69 | Fair | Investigate, check logs |
| <50 | Poor | Debug immediately |

### Common Issues

**Issue**: Audio cutting/popping
- **Cause**: Network jitter or high packet loss
- **Solution**: Deploy on AWS (reduces network latency)

**Issue**: Long silence between turns
- **Cause**: STT latency or LLM slow response
- **Solution**: Check Fix #2 (metadata timeout) and Fix #4 (retry capping)

**Issue**: Mono instead of stereo
- **Cause**: Recording configuration issue
- **Solution**: Verify LiveKit recording settings

---

## Commands Reference

### Download
```bash
# List all recordings
python download_livekit_recordings.py --list

# Download recent
python download_livekit_recordings.py --recent 10

# Download by room name
python download_livekit_recordings.py --download room_name

# Download by recording ID
python download_livekit_recordings.py --download-id REC_ID
```

### Analyze
```bash
# Analyze one file
python analyze_call_quality.py recordings/room/file.webm

# Analyze all in directory
for f in recordings/**/*.webm; do
    python analyze_call_quality.py "$f"
done
```

### Playback
```bash
# List all
python playback_recordings.py --list

# Play
python playback_recordings.py --play file.webm

# Convert to MP3
python playback_recordings.py --convert file.webm

# Export metadata
python playback_recordings.py --export file.webm

# Delete
python playback_recordings.py --delete file.webm

# Storage usage
python playback_recordings.py --storage
```

---

## Workflow Examples

### Example 1: Quality Check After Deploy
```bash
# 1. Download latest recordings from AWS
python download_livekit_recordings.py --recent 3

# 2. Analyze each
for f in recordings/**/*.webm; do
    python analyze_call_quality.py "$f"
done

# 3. Play worst-scoring one to debug
python playback_recordings.py --play worst_recording.webm
```

### Example 2: Share with Team
```bash
# 1. Analyze problematic call
python analyze_call_quality.py recordings/room/problem.webm

# 2. Convert to MP3
python playback_recordings.py --convert problem.webm

# 3. Export metadata
python playback_recordings.py --export problem.webm

# 4. Share recordings/room/ folder with team
# Includes: problem.webm, problem.mp3, problem.json
```

### Example 3: Long-term Monitoring
```bash
# Daily: Download and analyze
python download_livekit_recordings.py --recent 5
for f in recordings/**/*.webm; do
    python analyze_call_quality.py "$f" &
done

# Weekly: Check storage
python playback_recordings.py --storage

# Monthly: Clean up old recordings
python playback_recordings.py --delete old_recording.webm
```

---

## Debugging Checklist

Before deploying new code:
- [ ] Download 3 recent recordings
- [ ] Analyze each for quality issues
- [ ] Listen to at least one end-to-end
- [ ] Check that quality score ≥ 80
- [ ] Compare metrics with previous calls
- [ ] Check agent_debug.log latency numbers

If quality drops:
1. Download latest recordings
2. Analyze for new issues
3. Check agent_debug.log for errors
4. Compare with previous good recording
5. Debug specific component (STT, LLM, TTS)

---

## Integration with Other Tools

### With agent_debug.log
```bash
# 1. Find call in logs
grep "Room: my-room" ../agent_debug.log

# 2. Find recording for that room
python download_livekit_recordings.py --download my-room

# 3. Analyze recording
python analyze_call_quality.py recordings/my-room/*.webm

# 4. Compare metrics in log vs quality analysis
```

### With n8n Webhooks
```bash
# 1. Check n8n logs for call completion
# 2. Find corresponding recording
python download_livekit_recordings.py --download room-from-webhook

# 3. Verify audio matches n8n transcript
python playback_recordings.py --play recording.webm
```

---

## Troubleshooting

### "No recordings found"
```bash
# Check LiveKit connection
echo "URL: $LIVEKIT_URL"
echo "Key: $LIVEKIT_API_KEY"

# Download should work if credentials are correct
python download_livekit_recordings.py --list
```

### "ffprobe not found"
```bash
# Install ffmpeg
brew install ffmpeg  # macOS
# or
sudo apt-get install ffmpeg  # Linux
```

### "No audio player found"
```bash
# Install media player
brew install vlc  # macOS
# or
sudo apt-get install vlc  # Linux

# Or manually open .webm file
```

---

## Next Steps

1. **Download**: `python download_livekit_recordings.py --recent 3`
2. **Analyze**: `python analyze_call_quality.py recordings/**/*.webm`
3. **Listen**: `python playback_recordings.py --play recording.webm`
4. **Debug**: Check logs if quality score < 80
5. **Deploy**: Ready for AWS when scores are ≥ 85

---

**Happy debugging!** 🎵🚀
