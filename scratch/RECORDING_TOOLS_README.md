# Call Recording Tools

Complete suite for downloading, analyzing, and managing LiveKit call recordings for testing and debugging.

---

## Scripts Overview

### 1. `download_livekit_recordings.py` - Download Recordings
**Purpose**: Retrieve call recordings from LiveKit Cloud storage.

**Features**:
- List all recordings in your LiveKit account
- Download specific recordings by room name or ID
- Download most recent recordings
- Batch download with progress tracking
- Auto-organize by date and room name
- Generate metadata JSON for reference

**Installation Requirements**:
```bash
pip install httpx python-dotenv
```

**Usage**:

```bash
# List all recordings
python download_livekit_recordings.py --list

# Download most recent 5 recordings
python download_livekit_recordings.py --recent 5

# Download all recordings for a specific room
python download_livekit_recordings.py --download room_name

# Download specific recording by ID
python download_livekit_recordings.py --download-id RECORDING_ID

# Download 10 most recent (custom count)
python download_livekit_recordings.py --recent 10
```

**Output**:
```
recordings/
├── room_name_1/
│   ├── recording_xyz_20260709_145530.webm
│   └── recording_abc_20260709_160215.webm
├── room_name_2/
│   └── recording_def_20260709_170830.webm
└── recordings_metadata.json
```

**Environment Variables Required** (in `.env`):
```
LIVEKIT_URL=wss://your-livekit-url
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
```

---

### 2. `analyze_call_quality.py` - Analyze Audio Quality
**Purpose**: Analyze downloaded recordings to identify audio quality issues.

**Features**:
- Extract audio metrics (sample rate, bitrate, codec)
- Detect quality problems
- Generate quality score (0-100)
- Provide recommendations for improvement
- Export analysis as JSON

**Installation Requirements**:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

**Usage**:

```bash
# Analyze a recording
python analyze_call_quality.py recordings/room_name/recording.webm

# Analyze all recordings in directory
for file in recordings/**/*.webm; do
    python analyze_call_quality.py "$file"
done
```

**Output Example**:
```
======================================================================
📊 CALL QUALITY ANALYSIS REPORT
======================================================================

📁 File: recording_xyz_20260709_145530.webm
⏱️  Duration: 45.3 seconds

🔊 Audio Metrics:
   Sample Rate: 24000 Hz
   Channels: 2
   Bitrate: 192 kbps
   Codec: opus

✅ Quality Score: 92/100 (Excellent)

✅ No issues detected

💡 Recommendations (1):
   • Consider increasing compression for long-term storage

======================================================================
```

**Quality Score Criteria**:
- **90-100**: Excellent (clear audio, no issues)
- **70-89**: Good (minor issues, acceptable)
- **50-69**: Fair (audio quality concerns)
- **<50**: Poor (significant problems)

---

### 3. `playback_recordings.py` - Manage & Play Recordings
**Purpose**: Browse, play, and manage your recording library.

**Features**:
- Browse recording library with metadata
- Play recordings with system audio player
- Convert WebM → MP3 for sharing
- Export metadata to JSON
- Delete recordings to save space
- Storage usage summary

**Installation Requirements**:
```bash
# Install ffmpeg (for conversion)
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Install audio player (one of these)
brew install vlc mpv ffmpeg
```

**Usage**:

```bash
# List all recordings
python playback_recordings.py --list

# Play a recording
python playback_recordings.py --play recording_xyz_20260709_145530.webm

# Convert to MP3 (for sharing/archiving)
python playback_recordings.py --convert recording_xyz_20260709_145530.webm

# Export metadata to JSON
python playback_recordings.py --export recording_xyz_20260709_145530.webm

# Delete a recording (with confirmation)
python playback_recordings.py --delete recording_xyz_20260709_145530.webm

# Show storage usage
python playback_recordings.py --storage
```

**Output Example**:
```
📁 AVAILABLE RECORDINGS:
┌──────┬──────────────────────────┬─────────────┬──────────┐
│ #    │ Filename                 │ Size (MB)   │ Date     │
├──────┼──────────────────────────┼─────────────┼──────────┤
│ 1    │ recording_xyz_202607091…  │ 3.2         │ 2026-07-09 │
│ 2    │ recording_abc_202607081…  │ 2.8         │ 2026-07-08 │
│ 3    │ recording_def_202607071…  │ 4.1         │ 2026-07-07 │
└──────┴──────────────────────────┴─────────────┴──────────┘

Total: 3 recording(s)
```

---

## Complete Workflow: Download → Analyze → Playback

### Step 1: Download Recent Recordings
```bash
# Download 3 most recent recordings
python download_livekit_recordings.py --recent 3

# Check what was downloaded
python playback_recordings.py --list
```

### Step 2: Analyze Quality
```bash
# Analyze all WebM files
for file in recordings/**/*.webm; do
    echo "Analyzing: $file"
    python analyze_call_quality.py "$file"
done
```

### Step 3: Review & Share
```bash
# Play one for manual review
python playback_recordings.py --play recording_xyz.webm

# Convert to MP3 for sharing with team
python playback_recordings.py --convert recording_xyz.webm

# Export metadata
python playback_recordings.py --export recording_xyz.webm
```

### Step 4: Cleanup
```bash
# Show storage usage
python playback_recordings.py --storage

# Delete old recordings
python playback_recordings.py --delete recording_abc.webm
```

---

## Understanding Call Recordings

### What Gets Recorded?
- **Both audio streams**: Agent + Customer (stereo)
- **Full conversation**: From room connect to disconnect
- **Automatic**: No manual setup required (handled by LiveKit)

### Where Are Recordings Stored?
- **By default**: LiveKit Cloud (`cloud.livekit.io`)
- **Can be configured**: Store on S3, GCS, or local server

### Recording Formats
- **Default**: WebM with Opus codec
- **Can convert**: MP3, WAV, MP4 via ffmpeg
- **Typical size**: ~100KB per second (~6MB per minute)

---

## Troubleshooting

### Issue: "No recordings found"
```
Possible causes:
1. Recording not enabled in LiveKit config
2. Wrong API credentials in .env
3. Recording expired (check retention policy)

Solution:
- Verify LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env
- Check LiveKit cloud dashboard for recordings
```

### Issue: "ffprobe not found" in analysis
```
Solution:
- Install ffmpeg: brew install ffmpeg (macOS)
- Or: sudo apt-get install ffmpeg (Linux)
```

### Issue: "No audio player found" when playing
```
Solution:
- Install one of: vlc, mpv, or ffplay
- Or manually open .webm file in media player
```

### Issue: Conversion to MP3 is slow
```
Reason: Real-time encoding, ~1 minute per 1 minute of audio
Solution:
- Be patient or use lower bitrate: python playback_recordings.py --convert file.webm --bitrate 96k
```

---

## Use Cases

### 1. Debug Audio Quality Issues
```bash
# Download problematic call
python download_livekit_recordings.py --download problem_room

# Analyze audio quality
python analyze_call_quality.py recordings/problem_room/*.webm

# Listen to recording
python playback_recordings.py --play recording.webm
```

### 2. Performance Testing
```bash
# Download call recordings from load test
python download_livekit_recordings.py --recent 10

# Analyze all for quality consistency
for file in recordings/**/*.webm; do
    python analyze_call_quality.py "$file"
done
```

### 3. Share with Team
```bash
# Convert recordings to MP3 for easier sharing
python playback_recordings.py --convert recording_xyz.webm

# Export metadata for documentation
python playback_recordings.py --export recording_xyz.webm

# Share recordings/ folder with team
```

### 4. Archive & Storage Management
```bash
# Check total storage used
python playback_recordings.py --storage

# Export all metadata
for file in recordings/**/*.webm; do
    python playback_recordings.py --export "$file"
done

# Delete old recordings to free space
python playback_recordings.py --delete old_recording.webm
```

---

## Integration with Agent Logging

The recordings complement the agent logs in `agent_debug.log`:

| Source | Contains |
|--------|----------|
| Recording (WebM) | Raw audio (both speakers) |
| Transcript in logs | Text of what was said |
| Latency metrics | Time-to-first-token, TTS delay |
| Call summary | n8n webhook data |

**Combined Analysis Example**:
1. Find call in logs: `grep "Room: my-room" agent_debug.log`
2. Download recording: `python download_livekit_recordings.py --download my-room`
3. Analyze audio: `python analyze_call_quality.py recordings/my-room/*.webm`
4. Compare with log latencies to find issues

---

## Performance & Storage

**Typical Metrics**:
- Download speed: Limited by LiveKit API (~1-2 MB/s)
- Analysis speed: ~1 second per minute of audio
- Conversion speed: Real-time (1 minute audio = 1 minute to convert)
- Storage: ~6MB per minute of audio (WebM), ~1MB per minute (MP3)

**Cost Considerations**:
- LiveKit Cloud egress: $5 per 100GB
- Recording storage: Included in LiveKit plan

---

## Best Practices

1. **Regular Downloads**: Download recent calls weekly for quality monitoring
2. **Archive**: Convert old calls to MP3 and delete WebM after analysis
3. **Metadata**: Always export metadata for documentation
4. **Cleanup**: Delete recordings >1 month old to save storage
5. **Backup**: Keep important analysis reports and metadata JSONs

---

## Support

For issues:
1. Check `.env` configuration
2. Verify LiveKit API credentials
3. Check ffmpeg installation for analysis
4. Review agent logs for call details

---

**Ready to analyze your calls!** 🎵
