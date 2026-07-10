"""
Inspect Supabase schema and export table structures.
Run: python scripts/inspect_schema.py
"""
import os
import json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import httpx

SUPABASE_URL = os.getenv("SUPABASE_REST_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_REST_URL or SUPABASE_API_KEY not set in .env")
    exit(1)

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def get_tables():
    """Get all tables from information_schema"""
    url = f"{SUPABASE_URL}/tables"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Error fetching tables: {e}")
        return []

def get_table_schema(table_name):
    """Get schema for a specific table"""
    url = f"{SUPABASE_URL}/{table_name}?limit=1&select=*"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            
            # Get column info from response headers or by examining first row
            result = resp.json()
            if result and len(result) > 0:
                return {
                    "columns": list(result[0].keys()),
                    "sample": result[0]
                }
            return {"columns": [], "sample": None}
    except Exception as e:
        print(f"Error fetching {table_name}: {e}")
        return None

def inspect_all_tables():
    """Inspect all tables and export schema"""
    print("=" * 80)
    print("SUPABASE SCHEMA INSPECTION")
    print("=" * 80)
    
    # Get list of tables by querying information_schema
    print("\n[1] Fetching table list...")
    url = f"{SUPABASE_URL.rstrip('/')}/information_schema.tables?schema=eq.public&select=table_name"
    
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            tables_data = resp.json()
    except Exception as e:
        print(f"Could not fetch from information_schema: {e}")
        print("Trying alternative method: querying common table names...\n")
        
        # Fallback: try common table names
        common_tables = [
            "customers", "agents", "properties", "calls", "ad_clicks",
            "leads", "follow_ups", "properties_amenities", "call_logs"
        ]
        tables_data = [{"table_name": t} for t in common_tables]
    
    if not tables_data:
        print("No tables found!")
        return
    
    tables = [t["table_name"] for t in tables_data]
    print(f"Found {len(tables)} tables: {', '.join(tables)}\n")
    
    schema = {}
    
    # Inspect each table
    for i, table_name in enumerate(tables, 1):
        print(f"[{i}] Inspecting '{table_name}'...")
        table_info = get_table_schema(table_name)
        
        if table_info:
            schema[table_name] = table_info
            print(f"    Columns: {', '.join(table_info['columns'])}")
            if table_info['sample']:
                print(f"    Sample row: {json.dumps(table_info['sample'], indent=6, default=str)[:200]}...")
        else:
            print(f"    ERROR: Could not fetch schema")
        print()
    
    # Save schema to file
    output_file = Path(__file__).parent.parent / "SCHEMA.json"
    with open(output_file, "w") as f:
        json.dump(schema, f, indent=2, default=str)
    
    print("=" * 80)
    print(f"Schema exported to: {output_file}")
    print("=" * 80)
    
    # Print summary
    print("\nSCHEMA SUMMARY:")
    print("=" * 80)
    for table_name, info in schema.items():
        print(f"\n{table_name.upper()}")
        print(f"  Columns ({len(info['columns'])}): {', '.join(info['columns'])}")
        if info['sample']:
            print(f"  Sample data: {list(info['sample'].values())[:3]}...")

if __name__ == "__main__":
    inspect_all_tables()
