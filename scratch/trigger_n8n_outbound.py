import httpx
import sys
import json

async def trigger_n8n_flow(phone: str, name: str = ""):
    n8n_url = "http://127.0.0.1:5678/webhook/ad-click"
    
    payload = {
        "customer_phone": phone,
        "customer_name": name,
        "property_id": "d1111111-1111-1111-1111-111111111111", # Seeded Bandra Sea Face Property
        "agent_id": "c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3",     # Priya Sharma
        "ad_source": "facebook",
        "ad_id": "fb_ad_12345",
        "campaign_name": "Bandra 2BHK June"
    }

    print(f"\n[n8n Outbound Trigger] POSTing payload to {n8n_url}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(n8n_url, json=payload)
            print(f"Status Code: {resp.status_code}")
            print(f"Response Body:\n{resp.text}")
            if resp.status_code == 200:
                print("OK: Webhook accepted by n8n. Check your n8n execution history to monitor the SIP dial progress!")
            else:
                print("Error: Webhook returned error code. Ensure n8n is running and the /ad-click webhook is active.")
        except Exception as e:
            print(f"Error: Connection error sending request to n8n: {e}")

if __name__ == "__main__":
    import asyncio
    
    phone = "+918369884236"
    name = ""
    
    if len(sys.argv) > 1:
        phone = sys.argv[1]
    if len(sys.argv) > 2:
        name = sys.argv[2]
        
    asyncio.run(trigger_n8n_flow(phone, name))
