#!/usr/bin/env python3
"""
Test LiveKit with JWT token (correct auth method)
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

print(f"API Key: {api_key[:15]}...")
print(f"API Secret: {api_secret[:15]}...")
print(f"URL: {livekit_url}")
print()

# Convert URL
url = livekit_url.replace("wss://", "https://").replace("ws://", "http://")
print(f"REST API URL: {url}")
print()

# LiveKit uses JWT tokens for API auth
# The token format is: header.payload.signature

# Create JWT token manually
def create_jwt_token(api_key, api_secret):
    """Create a JWT token for LiveKit API access"""
    import base64
    import json
    import time
    import hmac
    import hashlib
    
    # Header
    header = {
        "alg": "HS256",
        "typ": "JWT"
    }
    
    # Payload - include grant claim
    now = int(time.time())
    payload = {
        "iss": api_key,
        "sub": api_key,
        "aud": "livekit",
        "iat": now,
        "exp": now + 3600,  # 1 hour expiry
        "grants": {
            "admin": True
        }
    }
    
    # Encode header and payload
    header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=').decode()
    payload_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
    
    # Create signature
    message = f"{header_encoded}.{payload_encoded}"
    signature = base64.urlsafe_b64encode(
        hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).digest()
    ).rstrip(b'=').decode()
    
    token = f"{message}.{signature}"
    return token

# Generate JWT token
jwt_token = create_jwt_token(api_key, api_secret)
print(f"Generated JWT Token: {jwt_token[:60]}...")
print()

# Test with JWT token
print("Testing with JWT Bearer token:")
try:
    resp = httpx.get(
        f"{url}/api/recordings",
        headers={"Authorization": f"Bearer {jwt_token}"},
        timeout=10
    )
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"  ✅ SUCCESS!")
        data = resp.json()
        print(f"  Recordings found: {len(data.get('items', []))}")
        print(f"  Response: {json.dumps(data, indent=2)[:500]}")
    else:
        print(f"  Error: {resp.text[:200]}")
        print(f"  Response headers: {dict(resp.headers)}")
except Exception as e:
    print(f"  Exception: {e}")
    import traceback
    traceback.print_exc()

print("\nDone!")
