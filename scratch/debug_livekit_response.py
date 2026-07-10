#!/usr/bin/env python3
"""
Debug LiveKit API response
"""
import os
import httpx
import base64
import json
import time
import hmac
import hashlib
from pathlib import Path

# Read .env file directly
env_file = Path.cwd().parent / ".env"
env_vars = {}

with open(env_file) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            key, value = line.strip().split("=", 1)
            env_vars[key] = value

api_key = env_vars.get("LIVEKIT_API_KEY")
api_secret = env_vars.get("LIVEKIT_API_SECRET")
livekit_url = env_vars.get("LIVEKIT_URL")

# Convert URL
url = livekit_url.replace("wss://", "https://").replace("ws://", "http://")
print(f"REST API URL: {url}")

def create_jwt_token(api_key, api_secret):
    """Create a JWT token for LiveKit API access"""
    header = {
        "alg": "HS256",
        "typ": "JWT"
    }
    
    now = int(time.time())
    payload = {
        "iss": api_key,
        "sub": api_key,
        "aud": "livekit",
        "iat": now,
        "exp": now + 3600,
        "grants": {
            "admin": True
        }
    }
    
    header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=').decode()
    payload_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
    
    message = f"{header_encoded}.{payload_encoded}"
    signature = base64.urlsafe_b64encode(
        hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).digest()
    ).rstrip(b'=').decode()
    
    return f"{message}.{signature}"

jwt_token = create_jwt_token(api_key, api_secret)

# Test with JWT token
print("\nFetching recordings list:")
resp = httpx.get(
    f"{url}/api/recordings",
    headers={"Authorization": f"Bearer {jwt_token}"},
    timeout=10
)

print(f"Status: {resp.status_code}")
print(f"Headers: {dict(resp.headers)}")
print(f"Content-Length: {len(resp.content)}")
print(f"Text length: {len(resp.text)}")
print(f"Content (first 500 chars): {repr(resp.text[:500])}")
print(f"Content (bytes): {resp.content[:500]}")

if resp.status_code == 200:
    if resp.text:
        print("\nAttempting JSON parse...")
        try:
            data = resp.json()
            print(f"Parsed successfully!")
            print(f"Keys: {list(data.keys())}")
            print(f"Items: {len(data.get('items', []))}")
        except json.JSONDecodeError as e:
            print(f"JSON error: {e}")
    else:
        print("Response is empty (no content)")
