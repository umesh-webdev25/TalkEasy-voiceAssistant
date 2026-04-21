import os
import json
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from utils.logging_config import get_logger

logger = get_logger(__name__)

class CustomWebSearchService:
    """Custom web search service using direct HTTP requests to Tavily API"""
    
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")
        self.base_url = "https://api.tavily.com"
        self.cache = {}
        self.cache_duration = timedelta(minutes=5)
        self.session = None
        logger.info("🔍 Custom Web Search Service initialized")
    
    def is_configured(self) -> bool:
        """Check if Tavily API is properly configured"""
        return bool(self.api_key and self.api_key != "your_tavily_api_key_here")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def search_web(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Perform a web search using Tavily API and return results
        """
        if not self.is_configured():
            logger.warning("⚠️ Tavily API not configured")
            return []
        
        # Check cache first
        cache_key = f"{query}_{max_results}"
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if datetime.now() - timestamp < self.cache_duration:
                logger.info(f"📦 Using cached results for: {query}")
                return cached_data
        
        try:
            session = await self._get_session()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "include_images": False,
                "include_raw_content": False
            }
            
            async with session.post(
                f"{self.base_url}/search",
                headers=headers,
                json=payload,
                timeout=30
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results", [])
                    
                    # Cache the results
                    self.cache[cache_key] = (results, datetime.now())
                    logger.info(f"✅ Web search completed for: {query} ({len(results)} results)")
                    return results
                else:
                    error_text = await response.text()
                    logger.error(f"Tavily API error {response.status}: {error_text}")
                    return []
                    
        except asyncio.TimeoutError:
            logger.error("Tavily API request timed out")
            return []
        except Exception as e:
            logger.error(f"Tavily search failed: {str(e)}")
            return []
    
    def format_search_results(self, search_results: List[Dict], query: str) -> str:
        """
        Format search results for LLM consumption
        """
        if not search_results:
            return f"No web search results found for: {query}"
        
        formatted = f"WEB SEARCH RESULTS FOR: {query}\n\n"
        
        for i, result in enumerate(search_results[:3], 1):
            title = result.get("title", "No title")
            url = result.get("url", "No URL")
            content = result.get("content", "No content available")
            
            formatted += f"RESULT {i}:\n"
            formatted += f"Title: {title}\n"
            formatted += f"URL: {url}\n"
            formatted += f"Content: {content[:500]}{'...' if len(content) > 500 else ''}\n\n"
        
        formatted += "Please use these search results to provide accurate information to the user."
        return formatted
    
    async def close(self):
        """Close the HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()

# Singleton instance for easy access
custom_web_search_service = CustomWebSearchService()
