import logging
import os
from services.custom_web_search_service import custom_web_search_service as web_search_service
from services.news_service import NewsService

logger = logging.getLogger(__name__)

class SkillsManager:
    """Manager for handling special skills in the voice agent"""
    
    def __init__(self):
        self.skills = {
            "news": NewsService(os.getenv("NEWS_API_KEY")),  # Registering the news service
            "web_search": web_search_service
        }
        logger.info("🛠 Skills Manager initialized with available skills: news, web_search")
    
    def get_skill(self, skill_name: str):
        """Retrieve a skill by name"""
        skill = self.skills.get(skill_name)
        if skill:
            logger.info(f"Retrieved skill: {skill_name}")
            return skill
        else:
            logger.warning(f"Skill not found: {skill_name}")
            return None
    
    def list_skills(self):
        """List all available skills"""
        return list(self.skills.keys())

# Singleton instance for easy access
skills_manager = SkillsManager()
