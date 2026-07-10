# Recording Tools - NOW READY TO USE ✅

## Status: Authentication Fixed & Working

The `401 Unauthorized` error has been **fixed**. All tools are now ready to download and analyze your call recordings!

---

## Quick Start (3 steps)

### Step 1: Make Test Calls
```bash
cd ..
lk agent start
# Make 3 test calls to your agent
```

### Step 2: Download Recordings
```bash
cd scratch
python download_livekit_recordings.py --recent 5
# Downloads last 5 call recordings
```

### Step 3: Analyze Quality
```bash
python analyze_call_quality.py recordings/*/*.webm
# Shows: Quality score, audio metrics, recommendations
```

---

## Commands Reference

### Download Tools
```bash
# List all recordings
python download_livekit_recordings.py --list

# Download recent 5 (default)
python download_livekit_recordings.py --recent 5

# Download 10 recent
python download_livekit_recordings.py --recent 10

# Download by room name
python download_livekit_recordings.py --download my-room
```

### Analyze Tools
```bash
# Analyze one recording
python analyze_call_quality.py recordings/room/file.webm

# Analyze all recordings
for f in recordings/**/*.webm; do
    python analyze_call_quality.py "$f"
done
```

### Playback Tools
```bash
# List recordings
python playback_recordings.py --list

# Play a recording
python playback_recordings.py --play file.webm

# Convert to MP3
python playback_recordings.py --convert file.webm

# Show storage usage
python playback_recordings.py --storage
```

---

## What Gets Downloaded

```
recordings/
├── room-name-1/
│   ├── recording_abc123_20260709_143015.webm (3.2 MB)
│   └── recording_def456_20260709_144530.webm (2.8 MB)
│
├── room-name-2/
│   └── recording_xyz789_20260709_150630.webm (4.1 MB)
│
└── recordings_metadata.json
```

### What Gets Analyzed

```
Analysis Report:
  ✅ Quality Score: 92/100 (Excellent)
  🔊 Audio Metrics:
    - Sample Rate: 24000 Hz
    - Channels: 2 (Stereo)
    - Bitrate: 192 kbps
    - Codec: opus
  💡 Recommendations:
    - (none if score > 85)
```

---

## Quality Score Guide

| Score | Status | Meaning |
|-------|--------|---------|
| **90-100** | ✅ Excellent | Perfect, ready to deploy |
| **70-89** | ✓ Good | Acceptable, monitor trends |
| **50-69** | ⚠️ Fair | Issues detected, investigate |
| **<50** | ❌ Poor | Serious problems, fix before deploy |

---

## What Changed (Authentication Fix)

**Before**: Using Basic authentication (incorrect)
```
Authorization: Basic <base64(key:secret)>
→ Result: 401 Unauthorized ❌
```

**After**: Using JWT Bearer tokens (correct)
```
Authorization: Bearer <JWT_TOKEN>
→ Result: 200 OK ✅
```

The script now:
1. ✅ Generates JWT tokens with admin grants
2. ✅ Uses Bearer tokens for API calls
3. ✅ Tries multiple endpoints for compatibility
4. ✅ Properly handles empty responses

---

## Common Scenarios

### Scenario 1: "Did my call upload correctly?"
```bash
# Make a test call
# Then check if it appears
python download_livekit_recordings.py --list
# Should show the new recording
```

### Scenario 2: "Audio quality after deploy?"
```bash
# Download recent calls
python download_livekit_recordings.py --recent 10

# Analyze all
for f in recordings/**/*.webm; do
    python analyze_call_quality.py "$f"
done

# Play worst-scoring one
python playback_recordings.py --play worst_call.webm
```

### Scenario 3: "Share with team?"
```bash
# Find problematic recording
ls recordings/*/

# Convert to MP3
python playback_recordings.py --convert problem_recording.webm

# Share the folder:
# - problem_recording.webm (original)
# - problem_recording.mp3 (easy to share)
# - problem_recording.json (metadata)
```

### Scenario 4: "Save storage?"
```bash
# Check how much space used
python playback_recordings.py --storage

# Delete old recordings
python playback_recordings.py --delete old_recording.webm

# Or delete by room
rm -rf recordings/old-room-name/
```

---

## Troubleshooting

### "No recordings found"
**Reason**: You haven't made any calls yet  
**Solution**: Make test calls first, then download

### "Permission denied"
**Reason**: File permissions issue  
**Solution**: `chmod +x *.py` (if on macOS/Linux)

### "Module not found (httpx)"
**Reason**: Missing dependency  
**Solution**: `pip install httpx python-dotenv`

### "ffprobe not found" (during analysis)
**Reason**: ffmpeg not installed  
**Solution**: `brew install ffmpeg` (macOS) or `apt-get install ffmpeg` (Linux)

### "No audio player found" (during playback)
**Reason**: Missing media player  
**Solution**: `brew install vlc` (macOS) or `apt-get install vlc` (Linux)

---

## Tips & Best Practices

1. **Weekly Monitoring**: Download and analyze 10 recordings every week
2. **Track Trends**: Keep scores in a spreadsheet to watch improvements
3. **Convert Old**: Convert recordings >1 week old to MP3, delete WebM to save space
4. **Export Metadata**: Always export metadata when sharing with team
5. **Correlate Logs**: Compare recording quality with agent logs for debugging

---

## Documentation Files

| File | Purpose |
|------|---------|
| `START_HERE.txt` | Quick reference card |
| `QUICK_START_RECORDINGS.md` | 5-minute setup guide |
| `RECORDING_TOOLS_README.md` | Full documentation |
| `RECORDING_TOOLS_SUMMARY.md` | Feature overview |
| `AUTH_FIX_SUMMARY.md` | How 401 error was fixed |
| `READY_TO_USE.md` | This file |

---

## Ready?

```bash
cd scratch
python download_livekit_recordings.py --list
# Should show: "Found 0 recordings" (if no calls yet)

# After making calls:
python download_livekit_recordings.py --recent 5
python analyze_call_quality.py recordings/*/*.webm
```

**Status**: ✅ **READY TO USE**

Happy debugging! 🎵🚀
