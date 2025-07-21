"""
Enhanced chat processor with language-aware routing for handling user messages.

This module provides intelligent chat processing with:
1. Automatic language detection
2. Language-specific document routing
3. Smart fallback mechanisms
4. Optimized multilingual responses

Features:
- Auto-detects Arabic vs English queries
- Routes to appropriate language documents
- Fallback to cross-language search when needed
- Preserves conversation context and flow
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
import re

from athr360.services.gemini_service import GeminiService
from athr360.core.adapters.llm_gemini import LLMServiceAdapter   
from athr360.core.rag.engine import RAG
from athr360.services.language_router import detect_query_language_simple, is_arabic_query, is_english_query
from athr360.utils.result import Result, Success
from athr360.utils.di import get_vector_store

logger = logging.getLogger(__name__)

class LanguageAwareChatProcessor:
    """
    Enhanced processor with automatic language detection and routing.
    
    Features:
    - Automatic language detection per message
    - Language-specific document filtering
    - Smart fallback to cross-language search
    - Optimized for Arabic/English bilingual support
    """
    
    def __init__(self, llm_service: Optional[GeminiService] = None, enable_language_routing: bool = True):
        """
        Initialize the language-aware chat processor.
        
        Args:
            llm_service: Service for LLM interaction (optional)
            enable_language_routing: Enable automatic language detection and routing
        """
        # Create or use the provided LLM service
        self.llm_service = llm_service or GeminiService()
        
        # Create enhanced RAG with language-aware capabilities
        self.rag = RAG(
            llm_provider=LLMServiceAdapter(self.llm_service),
            vector_store=get_vector_store(),
            enable_language_routing=enable_language_routing
        )
        
        self.enable_language_routing = enable_language_routing
        
        # Initialize language statistics
        self._language_stats = None
        self._update_language_stats()
        
        logger.info(f"Language-aware ChatProcessor initialized (routing: {enable_language_routing})")
    
    async def _update_language_stats(self):
        """Update language distribution statistics."""
        try:
            self._language_stats = await self.rag.get_language_statistics()
            logger.info(f"Language distribution: {self._language_stats}")
        except Exception as e:
            logger.warning(f"Could not get language statistics: {e}")
            self._language_stats = {}
    
    def _detect_and_log_language(self, user_message: str) -> str:
        """Detect language and log for monitoring."""
        if not self.enable_language_routing:
            return 'unknown'
        
        detected_lang = detect_query_language_simple(user_message)
        logger.debug(f"Language detection: '{user_message[:30]}...' -> {detected_lang}")
        return detected_lang
    
    def _should_use_cross_language_search(self, user_message: str, detected_lang: str) -> bool:
        """Determine if cross-language search should be enabled."""
        # Enable cross-language for:
        # 1. Mixed language queries
        # 2. Short queries that might benefit from more results
        # 3. Queries with low confidence in language detection
        
        if len(user_message.strip()) < 10:  # Very short queries
            return True
        
        # Check for mixed language indicators
        has_arabic = is_arabic_query(user_message)
        has_english = is_english_query(user_message)
        
        if has_arabic and has_english:  # Mixed language query
            return True
        
        # Check if we have sufficient documents in the detected language
        if self._language_stats and detected_lang in self._language_stats:
            doc_count = self._language_stats[detected_lang]
            if doc_count < 10:  # Too few documents in that language
                return True
        
        return False
    
    async def process_message(self,
                              user_message: str,
                              chat_history: Optional[List[str]] = None,
                              user_id: str = "anonymous",
                              system_override: Optional[str] = None,
                              force_language: Optional[str] = None
                              ) -> Result[Dict]:
        """
        Process a user message using language-aware RAG approach.
        
        Args:
            user_message: The message from the user
            chat_history: Optional list of previous message strings
            user_id: User identifier for tracking
            system_override: Optional system prompt override
            force_language: Force specific language ('ar', 'en', or None for auto-detect)
            
        Returns:
            Result containing the LLM response or error with language metadata
        """
        logger.debug(f"Processing message: '{user_message[:50]}...' for user {user_id}")
        
        # Language detection and routing configuration
        detected_lang = force_language or self._detect_and_log_language(user_message)
        enable_cross_language = self._should_use_cross_language_search(user_message, detected_lang)
        
        # Enhanced RAG query with language awareness
        rag_result = await self.rag.query(
            user_message,
            user_id=user_id,
            chat_history=chat_history,
            system_override=system_override,
            force_language=force_language,  # Pass force_language to RAG
            enable_cross_language=enable_cross_language
        )
        
        # Log language routing results
        if rag_result.is_success():
            response_data = rag_result.unwrap()
            confidence = response_data.get("confidence_level", "unknown")
            query_lang = response_data.get("query_language", "unknown")
            
            logger.debug(f"RAG response - Language: {query_lang}, Confidence: {confidence}")
            
            # Add enhanced metadata for language routing
            response_data["detected_language"] = detected_lang
            response_data["cross_language_enabled"] = enable_cross_language
            response_data["language_routing_used"] = self.enable_language_routing
            
            # Log for monitoring and debugging
            if confidence in ["low", "very_low"]:
                logger.info(f"Low confidence {confidence} for {detected_lang} query: '{user_message[:30]}...'")
        
        return rag_result
    
    async def process_message_streaming(self,
                                      user_message: str,
                                      chat_history: Optional[List[str]] = None,
                                      user_id: str = "anonymous",
                                      force_language: Optional[str] = None) -> AsyncGenerator[str, None]:
        """
        Process a user message with streaming response using language-aware routing.
        
        Args:
            user_message: The message from the user
            chat_history: Optional list of previous message strings
            user_id: User identifier for tracking
            force_language: Force specific language ('ar', 'en', or None)
            
        Yields:
            Chunks of the response as they are generated
        """
        logger.debug(f"Processing streaming message: '{user_message[:50]}...' for user {user_id}")
        
        # Language detection and routing configuration
        detected_lang = force_language or self._detect_and_log_language(user_message)
        enable_cross_language = self._should_use_cross_language_search(user_message, detected_lang)
        
        # Language-aware streaming RAG
        async for chunk in self.rag.query_streaming(
            user_message,
            chat_history=chat_history,
            force_language=force_language,
            enable_cross_language=enable_cross_language
        ):
            yield chunk
    
    async def get_language_info(self) -> Dict[str, Any]:
        """Get language routing information and statistics."""
        await self._update_language_stats()
        return {
            "language_routing_enabled": self.enable_language_routing,
            "available_languages": list(self._language_stats.keys()) if self._language_stats else [],
            "language_distribution": self._language_stats,
            "supports_arabic": await self.rag.is_language_available('ar'),
            "supports_english": await self.rag.is_language_available('en')
        }

# Maintain backward compatibility with existing ChatProcessor
class ChatProcessor(LanguageAwareChatProcessor):
    """
    Backward-compatible ChatProcessor that extends LanguageAwareChatProcessor.
    
    This maintains the existing API while providing enhanced language-aware capabilities.
    """
    
    def __init__(self, llm_service: Optional[GeminiService] = None):
        # Initialize with language routing enabled by default for better user experience
        super().__init__(llm_service=llm_service, enable_language_routing=True)
        logger.info("ChatProcessor initialized with enhanced language-aware capabilities")
        
    def _format_bullet_points(self, text: str) -> str:
        """
        Format bullet points to ensure proper spacing and prevent same-line issues.
        
        This method enforces strict formatting rules:
        - Every bullet point starts on a new line
        - Sub-items after colons are properly indented
        - No bullet points run together on the same line
        """
        if not text:
            return text
        
        # Step 1: Ensure bullet points never appear inline after colons
        # Pattern: "Text: • Item" should become "Text:\n• Item"
        text = re.sub(r':\s*•', ':\n\n•', text)
        
        # Step 2: Handle cases where multiple bullet points are on the same line
        # Pattern: "• Item1 • Item2" should become "• Item1\n\n• Item2"
        text = re.sub(r'(•[^•\n]+?)\s*•', r'\1\n\n•', text)
        
        # Step 3: Ensure bullet points after any non-newline character get proper spacing
        # Pattern: "text• Item" should become "text\n\n• Item"
        text = re.sub(r'([^\n])\s*•\s*', r'\1\n\n• ', text)
        
        # Step 4: Fix any bullet points that don't have proper spacing before them
        text = re.sub(r'(?<!\n\n)•', '\n\n•', text)
        
        # Step 5: Clean up excessive spacing (but preserve intentional double spacing)
        text = re.sub(r'\n{4,}', '\n\n', text)
        
        # Step 6: Ensure proper formatting between sections
        lines = text.split('\n')
        formatted_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if line.startswith('•'):
                # This is a bullet point
                formatted_lines.append(line)
                
                # Check if we need spacing after this bullet point
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # Add spacing before next bullet point or major section
                    if next_line.startswith('•') or next_line.startswith('**') or len(next_line) > 50:
                        formatted_lines.append('')
                        
            elif line.startswith('-') and len(formatted_lines) > 0:
                # This is a sub-item, should be indented
                formatted_lines.append(f"  {line}")
                
            elif line:
                # Regular text
                formatted_lines.append(line)
                
            else:
                # Empty line - preserve single empty lines, avoid excessive spacing
                if formatted_lines and formatted_lines[-1] != '':
                    formatted_lines.append('')
            
            i += 1
        
        # Step 7: Final formatting touches
        result = '\n'.join(formatted_lines)
        
        # Ensure the closing question has proper spacing
        result = re.sub(r'(?<!\n)\n(Is there anything else I can help you with\?)', r'\n\n\1', result)
        
        # Final cleanup of excessive newlines
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        # Ensure text doesn't start with newlines
        result = result.lstrip('\n')
        
        return result
        
    async def process_message_streaming(self,
                                      user_message: str,
                                      chat_history: Optional[List[str]] = None,
                                      user_id: str = "anonymous") -> AsyncGenerator[str, None]:
        """
        Process a user message with streaming response using permissive-first approach.
        
        Args:
            user_message: The message from the user
            chat_history: Optional list of previous message strings
            user_id: User identifier for tracking
            
        Yields:
            Chunks of the response as they are generated
        """
        logger.debug(f"Processing streaming message: '{user_message[:50]}...' for user {user_id}")
        
        # Permissive-first streaming: Always use RAG
        async for chunk in self.rag.query_streaming(
            user_message,
            chat_history=chat_history,
        ):
            yield chunk 