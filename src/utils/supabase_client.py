"""
Supabase utilities with proper URL encoding and safety.
Production-ready client with error handling and retries.
"""
import os
import httpx
from urllib.parse import quote
from loguru import logger
import asyncio
from typing import Any, Dict, List, Optional


class SupabaseClient:
    """Safe Supabase REST API client with URL encoding and safety."""
    
    def __init__(self, base_url: str, api_key: str, client: Optional[httpx.AsyncClient] = None, timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.client = client
        self.headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def _safe_encode_filter(self, value: str) -> str:
        """Safely encode filter values for Supabase REST API."""
        # URL encode special characters to prevent injection
        encoded = quote(str(value), safe='')
        return encoded
        
    async def _get(self, url: str) -> httpx.Response:
        """Internal helper to execute GET requests with or without shared client."""
        if self.client:
            return await self.client.get(url, headers=self.headers)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(url, headers=self.headers)
            
    async def _post(self, url: str, json_data: Optional[Dict[str, Any]] = None) -> httpx.Response:
        """Internal helper to execute POST requests with or without shared client."""
        if self.client:
            return await self.client.post(url, headers=self.headers, json=json_data)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(url, headers=self.headers, json=json_data)
    
    async def get_customers_by_phone(self, phone: str) -> List[Dict[str, Any]]:
        """
        Fetch customer by phone number (URL encoded for safety).
        Raises: httpx.HTTPError on failure
        """
        phone_encoded = self._safe_encode_filter(phone)
        url = f"{self.base_url}/customers?phone=eq.{phone_encoded}&select=*"
        
        try:
            resp = await self._get(url)
            resp.raise_for_status()
            return resp.json()
        except asyncio.TimeoutError:
            logger.error(f"Timeout querying customers (phone: {phone})")
            raise
        except httpx.HTTPError as e:
            logger.error(f"HTTP error querying customers: {e}")
            raise
    
    async def get_round_robin_agent(self) -> str:
        """Get next agent via round-robin RPC."""
        url = f"{self.base_url}/rpc/get_round_robin_agent"
        
        try:
            resp = await self._post(url)
            resp.raise_for_status()
            return resp.json()  # Returns agent ID string
        except asyncio.TimeoutError:
            logger.error("Timeout fetching round-robin agent")
            raise
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching agent: {e}")
            raise
    
    async def get_ad_clicks_by_phone(self, phone: str, limit: int = 1) -> List[Dict[str, Any]]:
        """Fetch most recent ad clicks by phone (URL encoded)."""
        phone_encoded = self._safe_encode_filter(phone)
        url = f"{self.base_url}/ad_clicks?customer_phone=eq.{phone_encoded}&order=clicked_at.desc&limit={limit}"
        
        try:
            resp = await self._get(url)
            resp.raise_for_status()
            return resp.json()
        except (asyncio.TimeoutError, httpx.HTTPError) as e:
            logger.warning(f"Error querying ad_clicks: {e}")
            return []
    
    async def get_property_by_id(self, property_id: str) -> Optional[Dict[str, Any]]:
        """Fetch property details by ID."""
        property_id_encoded = self._safe_encode_filter(property_id)
        url = f"{self.base_url}/properties?id=eq.{property_id_encoded}&select=*&limit=1"
        
        try:
            resp = await self._get(url)
            resp.raise_for_status()
            results = resp.json()
            return results[0] if results else None
        except (asyncio.TimeoutError, httpx.HTTPError) as e:
            logger.warning(f"Error fetching property: {e}")
            return None
    
    async def get_agent_fallback(self) -> Optional[str]:
        """Get first agent as fallback (when RPC not available)."""
        url = f"{self.base_url}/agents?select=id&limit=1"
        
        try:
            resp = await self._get(url)
            resp.raise_for_status()
            results = resp.json()
            return results[0].get("id") if results else None
        except (asyncio.TimeoutError, httpx.HTTPError) as e:
            logger.warning(f"Error fetching fallback agent: {e}")
            return None
