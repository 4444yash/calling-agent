#!/usr/bin/env python3
"""
Test LiveKit API authentication
"""
import os
import sys
import httpx
import base64
from pathlib import Path

# Read .env file directly
env_file = Path(__file__).parent.parent / ".env"
if not env_file.exists():
    env_file = Path.cwd().parent / ".env"

print(f"Reading from: {env_file}")
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

# Try different auth methods
methods = [
    {
        "name": "Basic Auth (key:secret base64)",
        "header": f"Basic {base64.b64encode(f'{api_key}:{api_secret}'.encode()).decode()}"
    },
    {
        "name": "Bearer with key:secret",
        "header": f"Bearer {api_key}:{api_secret}"
    },
    {
        "name": "Bearer with key",
        "header": f"Bearer {api_key}"
    },
]

for method in methods:
    print(f"Testing: {method['name']}")
    print(f"  Header: {method['header'][:60]}...")
    
    try:
        resp = httpx.get(
            f"{url}/api/recordings",
            headers={"Authorization": method["header"]},
            timeout=10
        )
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"  ✅ SUCCESS!")
            data = resp.json()
            print(f"  Recordings: {len(data.get('items', []))}")
            break
        else:
            print(f"  Error: {resp.text[:100]}")
    except Exception as e:
        print(f"  Exception: {e}")
    print()

print("\nDone!")
