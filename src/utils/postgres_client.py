"""
PostgreSQL client for direct database queries (production self-hosted stack).
Replaces Supabase REST API when using EC2-hosted Postgres.

Usage:
    client = PostgresClient(
        host="localhost",
        database="agent_db",
        user="agent_user",
        password="secret"
    )
    customers = await client.get_customers_by_phone("+919876543210")
"""

import asyncpg
from loguru import logger
from typing import Any, Dict, List, Optional
import asyncio


class PostgresClient:
    """Direct PostgreSQL client with connection pooling."""
    
    def __init__(self, host: str, port: int = 5432, database: str = "agent_db",
                 user: str = "agent_user", password: str = "password"):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Initialize connection pool."""
        try:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=2,
                max_size=10,
                command_timeout=5.0
            )
            logger.info(f"✓ Postgres pool connected ({self.host}:{self.port}/{self.database})")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Postgres: {e}")
            raise
    
    async def disconnect(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("✓ Postgres pool closed")
    
    async def get_customers_by_phone(self, phone: str) -> List[Dict[str, Any]]:
        """Fetch customer by phone number."""
        if not self.pool:
            raise RuntimeError("Pool not initialized. Call .connect() first.")
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM customers WHERE phone = $1 LIMIT 1""",
                    phone
                )
                return [dict(row) for row in rows]
        except asyncio.TimeoutError:
            logger.error(f"Timeout querying customers (phone: {phone})")
            raise
        except Exception as e:
            logger.error(f"Error querying customers: {e}")
            raise
    
    async def get_round_robin_agent(self) -> str:
        """Get next agent via round-robin logic."""
        if not self.pool:
            raise RuntimeError("Pool not initialized. Call .connect() first.")
        
        try:
            async with self.pool.acquire() as conn:
                # Simple round-robin: get agent with lowest call count
                result = await conn.fetchval(
                    """
                    SELECT id FROM agents 
                    ORDER BY (SELECT COUNT(*) FROM calls WHERE agent_id = agents.id) ASC
                    LIMIT 1
                    """
                )
                return result or "default_agent"
        except Exception as e:
            logger.error(f"Error fetching agent: {e}")
            raise
    
    async def get_ad_clicks_by_phone(self, phone: str, limit: int = 1) -> List[Dict[str, Any]]:
        """Fetch most recent ad clicks by phone."""
        if not self.pool:
            raise RuntimeError("Pool not initialized. Call .connect() first.")
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM ad_clicks 
                       WHERE customer_phone = $1 
                       ORDER BY clicked_at DESC 
                       LIMIT $2""",
                    phone,
                    limit
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning(f"Error querying ad_clicks: {e}")
            return []
    
    async def get_property_by_id(self, property_id: str) -> Optional[Dict[str, Any]]:
        """Fetch property details by ID."""
        if not self.pool:
            raise RuntimeError("Pool not initialized. Call .connect() first.")
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT * FROM properties WHERE id = $1""",
                    property_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.warning(f"Error fetching property: {e}")
            return None
    
    async def get_agent_fallback(self) -> Optional[str]:
        """Get first agent as fallback."""
        if not self.pool:
            raise RuntimeError("Pool not initialized. Call .connect() first.")
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("""SELECT id FROM agents LIMIT 1""")
                return result
        except Exception as e:
            logger.warning(f"Error fetching fallback agent: {e}")
            return None
    
    # Convenience methods for trial/demo
    async def insert_call_record(self, call_data: Dict[str, Any]) -> str:
        """Insert a call record and return call_id."""
        if not self.pool:
            raise RuntimeError("Pool not initialized. Call .connect() first.")
        
        try:
            async with self.pool.acquire() as conn:
                call_id = await conn.fetchval(
                    """INSERT INTO calls (customer_phone, duration, transcript, metadata)
                       VALUES ($1, $2, $3, $4)
                       RETURNING id""",
                    call_data.get("phone"),
                    call_data.get("duration", 0),
                    call_data.get("transcript", ""),
                    call_data.get("metadata", {})
                )
                return call_id
        except Exception as e:
            logger.error(f"Error inserting call record: {e}")
            raise
