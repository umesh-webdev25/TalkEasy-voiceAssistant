import google.generativeai as genai
from typing import List, Dict, Optional, AsyncGenerator, Union
import logging
from services.custom_web_search_service import custom_web_search_service as web_search_service
from services.skills_manager import skills_manager

logger = logging.getLogger(__name__)


class LLMService:    
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", persona: str = None):
        self.api_key = api_key
        self.model_name = model_name
        self.persona = persona or "helpful AI assistant"
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        logger.info(f"🤖 LLM Service initialized with model: {model_name}, persona: {self.persona}")
    
    def set_persona(self, persona: str):
        """Set the persona for the LLM service"""
        persona_prompts = {
            "default": "a helpful AI assistant",
            "pirate": "a friendly pirate who speaks with nautical terms and pirate slang like 'Arrr', 'matey', 'shiver me timbers', and 'yo ho ho'",
            "developer": "a knowledgeable software developer who explains technical concepts clearly and uses programming examples when appropriate",
            "cowboy": "an old west cowboy who speaks with western slang like 'howdy partner', 'yeehaw', 'varmint', and 'rootin' tootin'",
            "robot": "a logical robot who speaks with technical precision, uses binary references, and says 'beep boop' occasionally"
        }
        
        self.persona = persona_prompts.get(persona, persona_prompts["default"])
        logger.info(f"🤖 Persona switched to: {self.persona}")

    def _detect_language(self, text: str) -> str:
        """Simple detection: returns 'hi' if Devanagari chars present, otherwise 'en'"""
        if not text:
            return "en"
        for ch in text:
            if '\u0900' <= ch <= '\u097F':  # Devanagari block
                return "hi"
        return "en"
    
    def format_chat_history_for_llm(self, messages: List[Dict]) -> str:
        if not messages:
            return ""
        
        formatted_history = "\n\nPrevious conversation context:\n"
        for msg in messages :
            role = "User" if msg["role"] == "user" else "Assistant"
            formatted_history += f"{role}: {msg['content']}\n"
        
        return formatted_history
    
    def _should_perform_web_search(self, user_message: str) -> bool:
        """Determine if a web search should be performed based on the user message"""
        search_triggers = [
            'search for', 'search google for', 'search google', 'find information about', 'look up', 
            'what is', 'who is', 'when is', 'where is', 'how to',
            'latest news about', 'recent developments in',
            'tell me about', 'information on', 'details about'
        ]
        
        user_message_lower = user_message.lower()
        
        # Check for explicit search commands
        if any(trigger in user_message_lower for trigger in ['search for', 'search google for', 'search google', 'find information about', 'look up', 'tell me about']):
            return True
        
        # Check for information-seeking questions that would benefit from current data
        if any(user_message_lower.startswith(trigger) for trigger in ['what is', 'who is', 'when is', 'where is', 'how to']):
            return True
        
        # Check for topics that require current information
        current_info_topics = ['news', 'weather', 'stock', 'price', 'recent', 'latest', 'current', 'today', 'now']
        if any(topic in user_message_lower for topic in current_info_topics):
            return True
        
        return False
    
    def _extract_search_query(self, user_message: str) -> str:
        """Extract the search query from the user message"""
        user_message_lower = user_message.lower()
        
        # Remove common search phrases to get the actual query
        search_phrases = [
            'search for', 'search google for', 'search google', 'find information about', 'look up', 
            'what is', 'who is', 'when is', 'where is', 'how to',
            'tell me about', 'information on', 'details about'
        ]
        
        for phrase in search_phrases:
            if phrase in user_message_lower:
                return user_message_lower.split(phrase, 1)[1].strip()
        
        # If no specific phrase found, use the entire message as query
        return user_message.strip()

    def _extract_news_category(self, user_message: str) -> str:
        """Extract the news category from the user message"""
        user_message_lower = user_message.lower()
        
        # Define common news categories and their keywords
        categories = {
            'business': ['business', 'finance', 'economy', 'market', 'stock'],
            'technology': ['technology', 'tech', 'ai', 'artificial intelligence', 'computer'],
            'sports': ['sports', 'football', 'basketball', 'soccer', 'baseball'],
            'entertainment': ['entertainment', 'movie', 'music', 'celebrity', 'hollywood'],
            'health': ['health', 'medical', 'medicine', 'covid', 'pandemic'],
            'science': ['science', 'research', 'discovery', 'space', 'nasa']
        }
        
        # Check for specific category keywords
        for category, keywords in categories.items():
            if any(keyword in user_message_lower for keyword in keywords):
                return category
        
        # Default to general news
        return "general"

    def _format_news_response(self, news_data: dict, category: str) -> str:
        """Format the news response for the user"""
        articles = news_data.get("articles", [])
        if not articles:
            return "No news articles found for this category."
        
        # Get top 3 articles
        top_articles = articles[:3]
        
        response = f"Here are the latest {category} news headlines:\n\n"
        
        for i, article in enumerate(top_articles, 1):
            title = article.get("title", "No title available")
            source = article.get("source", {}).get("name", "Unknown source")
            response += f"{i}. {title} - {source}\n"
        
        response += "\nWould you like me to read any of these articles in detail?"
        return response
    
    async def generate_response(self, user_message: str, chat_history: List[Dict], language: str = "auto") -> str:
        try:
            # Resolve language preference
            lang = language
            if language == "auto":
                lang = self._detect_language(user_message)

            if lang == "both":
                language_instruction = "Provide the answer in BOTH English and Hindi. First provide the English version, then the Hindi translation separated by '---'."
            elif lang == "hi":
                language_instruction = "Respond in Hindi only."
            else:
                language_instruction = "Respond in English only."
            
            # Check if web search is needed
            if self._should_perform_web_search(user_message):
                query = self._extract_search_query(user_message)
                logger.info(f"🔍 Performing web search for query: {query}")
                
                try:
                    search_results = await web_search_service.search_web(query)
                    formatted_results = web_search_service.format_search_results(search_results, query)
                    
                    # Combine search results with LLM processing for better response
                    history_context = self.format_chat_history_for_llm(chat_history)
                    
                    enhanced_prompt = f"""You are {self.persona}. Based on the following search results, provide a comprehensive answer to the user's question.

SEARCH RESULTS FOR "{query}":
{formatted_results}

USER'S ORIGINAL QUESTION: "{user_message}"

{history_context}

Please provide a helpful, accurate answer based on the search results.
Summarize the key information and cite relevant sources if appropriate."""
                    # append language instruction
                    enhanced_prompt = f"{language_instruction}\n\n{enhanced_prompt}"
                    
                    llm_response = self.model.generate_content(enhanced_prompt)
                    
                    if llm_response.candidates:
                        response_text = ""
                        for part in llm_response.candidates[0].content.parts:
                            if hasattr(part, 'text'):
                                response_text += part.text
                        
                        if response_text.strip():
                            return response_text.strip()
                    
                    # Fallback to just returning formatted search results if LLM fails
                    return formatted_results
                    
                except Exception as search_error:
                    logger.error(f"Web search failed: {search_error}")
                    # Continue with normal LLM response if search fails
            

            # Check if news information is requested
            if any(keyword in user_message.lower() for keyword in ['news', 'headlines', 'latest news', 'current events', 'breaking news']):
                category = self._extract_news_category(user_message)
                logger.info(f"📰 Fetching news for category: {category}")
                news_service = skills_manager.get_skill("news")
                if news_service:
                    news_data = news_service.get_news_headlines(category)
                    if "error" not in news_data and "articles" in news_data and news_data["articles"]:
                        return self._format_news_response(news_data, category)
                    else:
                        return "I couldn't fetch the latest news at the moment. Please try again later."

            # Normal LLM response for non-search queries
            history_context = self.format_chat_history_for_llm(chat_history)
            
            llm_prompt = f"""{language_instruction}
You are {self.persona}. Please respond directly to the user's current question.

IMPORTANT: Always answer the CURRENT user question directly. Do not give generic responses about your capabilities unless specifically asked "what can you do".

User's current question: "{user_message}"



Please provide a specific, helpful answer to the user's current question. Keep your response under 3000 characters."""
            llm_response = self.model.generate_content(llm_prompt)
            
            if not llm_response.candidates:
                raise Exception("No response candidates generated from LLM")
            
            response_text = ""
            for part in llm_response.candidates[0].content.parts:
                if hasattr(part, 'text'):
                    response_text += part.text
            
            if not response_text.strip():
                raise Exception("Empty response text from LLM")
            
            response_text = response_text.strip()
            return response_text
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"LLM response generation error: {error_msg}")
            
            # Check for specific error types
            if "quota" in error_msg.lower() or "429" in error_msg:
                raise Exception("API quota exceeded. Please check your billing and rate limits.")
            elif "403" in error_msg or "unauthorized" in error_msg.lower():
                raise Exception("API authentication failed. Please check your API key.")
            elif "404" in error_msg or "not found" in error_msg.lower():
                raise Exception("Model not found. Please check the model name.")
            else:
                raise

    async def generate_streaming_response(self, user_message: str, chat_history: List[Dict], web_search_results: str = None, language: str = "auto") -> AsyncGenerator[str, None]:
        """Generate a streaming response from the LLM"""
        try:
            # Resolve language preference for streaming via same auto-detect helper if caller used tagging in message
            # Note: callers can include language preference by passing a special marker or by changing this method signature if desired.
            # For backwards compatibility, detection remains simple and based on Devanagari characters.
            # (If you want to pass explicit language param to streaming, update signature similarly.)
            # Respect explicit language param; fall back to auto-detect only when language=='auto'
            lang = language
            if language == "auto":
                lang = self._detect_language(user_message)

            if lang == "both":
                language_instruction = "Provide the answer in BOTH English and Hindi. First provide the English version, then the Hindi translation separated by '---'."
            elif lang == "hi":
                language_instruction = "Respond in Hindi only."
            else:
                language_instruction = "Respond in English only."
            
            # Check if news information is requested
            if any(keyword in user_message.lower() for keyword in ['news', 'headlines', 'latest news', 'current events', 'breaking news']):
                 category = self._extract_news_category(user_message)
                 logger.info(f"📰 Fetching news for category: {category}")
                 news_service = skills_manager.get_skill("news")
                 if news_service:
                     news_data = news_service.get_news_headlines(category)
                     if "error" not in news_data and "articles" in news_data and news_data["articles"]:
                         news_response = self._format_news_response(news_data, category)
                         # Yield the news response as a single chunk
                         yield news_response
                         return
                     else:
                         yield "I couldn't fetch the latest news at the moment. Please try again later."
                         return

            history_context = self.format_chat_history_for_llm(chat_history)
            
            # Build the prompt with web search results if provided
            if web_search_results:
                llm_prompt = f"""You are {self.persona}. Please respond directly to the user's current question using the provided web search results.
 
 IMPORTANT: Always answer the CURRENT user question directly. Do not give generic responses about your capabilities unless specifically asked "what can you do".
 
 WEB SEARCH RESULTS:
 {web_search_results}
 
 User's current question: "{user_message}"
 
 {history_context}
 
 Please provide a specific, helpful answer to the user's current question based on the web search results.
 Summarize the key information and cite relevant sources if appropriate. Keep your response under 3000 characters."""
            else:
                llm_prompt = f"""You are {self.persona}. Please respond directly to the user's current question.
 
 IMPORTANT: Always answer the CURRENT user question directly. Do not give generic responses about your capabilities unless specifically asked "what can you do".
 
 User's current question: "{user_message}"
 
 {history_context}
 
 Please provide a specific, helpful answer to the user's current question. Keep your response under 3000 characters."""
            
            # Prepend language instruction
            llm_prompt = f"{language_instruction}\n\n{llm_prompt}"

            # Use stream_generate_content for streaming response
            response_stream = self.model.generate_content(llm_prompt, stream=True)

            accumulated_response = ""
            for chunk in response_stream:
                if chunk.candidates and len(chunk.candidates) > 0:
                    candidate = chunk.candidates[0]
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                accumulated_response += part.text
                                yield part.text
            
            if not accumulated_response.strip():
                raise Exception("Empty response text from LLM")
            
            logger.info(f"LLM streaming response completed: {len(accumulated_response)} characters")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"LLM streaming response generation error for '{user_message[:50]}...': {error_msg}")
            
            # Check for specific error types
            if "quota" in error_msg.lower() or "429" in error_msg:
                logger.error("❌ API quota exceeded or rate limited")
                raise Exception("API quota exceeded. Please check your billing and rate limits.")
            elif "403" in error_msg or "unauthorized" in error_msg.lower():
                logger.error("❌ API authentication failed")
                raise Exception("API authentication failed. Please check your API key.")
            elif "404" in error_msg or "model" in error_msg.lower():
                logger.error("❌ Model issue")
                raise Exception("Model issue. Please check the model name or availability.")
            else:
                raise
