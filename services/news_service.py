import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict

logger = logging.getLogger(__name__)

class NewsService:
    """Service for fetching news headlines using free RSS feeds."""
    
    def __init__(self, api_key: str = None):
        # API key parameter kept for compatibility but not used for free RSS feeds
        logger.info("📰 News Service initialized (using free RSS feeds)")

    def _parse_rss_feed(self, xml_content: str) -> List[Dict]:
        """Parse RSS feed XML and extract news articles."""
        try:
            root = ET.fromstring(xml_content)
            articles = []
            
            # Parse RSS feed items
            for item in root.findall('.//item'):
                title = item.find('title')
                link = item.find('link')
                description = item.find('description')
                pub_date = item.find('pubDate')
                
                article = {
                    'title': title.text if title is not None else 'No title',
                    'url': link.text if link is not None else '',
                    'description': description.text if description is not None else 'No description',
                    'publishedAt': pub_date.text if pub_date is not None else '',
                    'source': {'name': 'Google News RSS'}
                }
                articles.append(article)
            
            return articles
        except Exception as e:
            logger.error(f"Error parsing RSS feed: {str(e)}")
            return []

    def get_news_headlines(self, category: str = "general") -> dict:
        """Fetch current news headlines for a given category using free RSS feeds."""
        try:
            # Use direct RSS feed parsing with feedparser library
            import feedparser
            
            rss_feeds = {
                "general": "https://feeds.bbci.co.uk/news/rss.xml",
                "technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
                "business": "https://feeds.bbci.co.uk/news/business/rss.xml",
                "sports": "https://feeds.bbci.co.uk/news/sport/rss.xml",
                "entertainment": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
                "health": "https://feeds.bbci.co.uk/news/health/rss.xml",
                "science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"
            }
            
            rss_url = rss_feeds.get(category, rss_feeds["general"])
            
            # Parse the RSS feed
            feed = feedparser.parse(rss_url)
            
            # Format the response to match the expected structure
            articles = []
            for entry in feed.entries[:10]:  # Limit to 10 articles
                article = {
                    "title": entry.get("title", "No title"),
                    "url": entry.get("link", ""),
                    "description": entry.get("description", "No description"),
                    "publishedAt": entry.get("published", ""),
                    "source": {"name": "BBC News"}
                }
                articles.append(article)
            
            news_data = {
                "status": "ok",
                "totalResults": len(articles),
                "articles": articles
            }
            
            logger.info(f"News data retrieved for category {category}: {len(articles)} articles")
            return news_data
            
        except Exception as e:
            logger.error(f"Error fetching news data: {str(e)}")
            return {"error": "Could not fetch news data.", "status": "error"}
