# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download LiveKit agent model files (Silero VAD, turn detector, etc.)
RUN python -c "from livekit.agents.inference import _utils; _utils.download_model_files()" 2>/dev/null || true

# Copy application code
COPY agent.py .
COPY .env .

ENTRYPOINT ["python", "agent.py"]
CMD ["start"]
