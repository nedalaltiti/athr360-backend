"""
Language-aware query routing service.

This service detects user query language and intelligently routes searches
to the appropriate language-specific documents in the vector database.

Features:
- Automatic language detection
- Smart query routing
- Fallback mechanisms
- Language preference handling
"""

import logging
import re
from typing import Optional, List
from dataclasses import dataclass

from athr360.core.document import Document
from athr360.infrastructure.vector_store import VectorStore

logger = logging.getLogger(__name__)

@dataclass
class LanguageDetectionResult:
    """Result of language detection analysis."""
    detected_language: str
    confidence: float
    arabic_percentage: float
    english_percentage: float
    
class LanguageAwareQueryRouter:
    """
    Smart query router that automatically detects language and routes queries
    to the appropriate language-filtered search.
    """
    
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self.language_stats = None
        self._update_language_stats()
    
    def _update_language_stats(self):
        """Update language statistics from the vector store."""
        try:
            self.language_stats = self.vector_store.get_language_statistics()
            logger.info(f"Language distribution in vector store: {self.language_stats}")
        except Exception as e:
            logger.warning(f"Could not get language statistics: {e}")
            self.language_stats = {}
    
    def detect_query_language(self, query: str) -> LanguageDetectionResult:
        """
        Detect the language of a query string with confidence scoring.
        
        Args:
            query: User query string
            
        Returns:
            LanguageDetectionResult with detected language and confidence
        """
        if not query or not query.strip():
            return LanguageDetectionResult('unknown', 0.0, 0.0, 0.0)
        
        # Clean query for analysis
        clean_query = re.sub(r'[^\w\s]', '', query).strip()
        
        # Count Arabic characters (comprehensive Unicode ranges)
        arabic_pattern = r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]'
        arabic_chars = len(re.findall(arabic_pattern, clean_query))
        
        # Count English characters
        english_chars = len(re.findall(r'[A-Za-z]', clean_query))
        
        # Total meaningful characters
        total_chars = arabic_chars + english_chars
        
        if total_chars == 0:
            return LanguageDetectionResult('unknown', 0.0, 0.0, 0.0)
        
        # Calculate percentages
        arabic_percentage = arabic_chars / total_chars
        english_percentage = english_chars / total_chars
        
        # Determine language with confidence
        if arabic_percentage > 0.7:
            return LanguageDetectionResult('ar', 0.9, arabic_percentage, english_percentage)
        elif english_percentage > 0.7:
            return LanguageDetectionResult('en', 0.9, arabic_percentage, english_percentage)
        elif arabic_percentage > 0.5:
            return LanguageDetectionResult('ar', 0.7, arabic_percentage, english_percentage)
        elif english_percentage > 0.5:
            return LanguageDetectionResult('en', 0.7, arabic_percentage, english_percentage)
        elif arabic_percentage > english_percentage:
            return LanguageDetectionResult('ar', 0.5, arabic_percentage, english_percentage)
        else:
            return LanguageDetectionResult('en', 0.5, arabic_percentage, english_percentage)
    
    async def smart_search(
        self,
        query: str,
        k: int = 5,
        *,
        force_language: Optional[str] = None,
        fallback_to_all: bool = True,
        enable_cross_language: bool = False
    ) -> List[Document]:
        """
        Smart search that automatically detects language and filters results.
        
        Args:
            query: Search query
            k: Number of results
            force_language: Force a specific language ('ar', 'en', or None)
            fallback_to_all: If no results in detected language, search all languages
            enable_cross_language: Allow mixed language results with preference
            
        Returns:
            Language-appropriate search results
        """
        logger.debug(f"Smart search for query: '{query[:50]}...', force_language: {force_language}")
        
        # Detect or use forced language
        if force_language:
            detected_lang = force_language
            confidence = 1.0
            logger.debug(f"Using forced language: {force_language}")
        else:
            detection = self.detect_query_language(query)
            detected_lang = detection.detected_language
            confidence = detection.confidence
            logger.debug(f"Detected language: {detected_lang} (confidence: {confidence:.2f})")
        
        # Check if we have documents in the detected language
        if self.language_stats and detected_lang in self.language_stats:
            available_docs = self.language_stats[detected_lang]
            logger.debug(f"Available documents in '{detected_lang}': {available_docs}")
        
        # Strategy 1: Try language-specific search first
        results = []
        if detected_lang != 'unknown' and confidence > 0.4:
            try:
                results = await self.vector_store.similarity_search(
                    query=query,
                    k=k,
                    language_filter=detected_lang
                )
                
                if results:
                    logger.debug(f"Language-filtered search successful: {len(results)} results for '{detected_lang}'")
                    return results
                else:
                    logger.debug(f"No results found for language filter: {detected_lang}")
                    
            except Exception as e:
                logger.warning(f"Language-filtered search failed: {e}")
        
        # Strategy 2: Cross-language search with preference
        if enable_cross_language and not results and detected_lang != 'unknown':
            try:
                results = await self.vector_store.similarity_search(
                    query=query,
                    k=k,
                    language_preference=detected_lang  # Boost detected language
                )
                
                if results:
                    logger.debug(f"Cross-language search with preference successful: {len(results)} results")
                    return results
                    
            except Exception as e:
                logger.warning(f"Cross-language search failed: {e}")
        
        # Strategy 3: Fallback to all languages
        if fallback_to_all and not results:
            try:
                results = await self.vector_store.similarity_search(
                    query=query,
                    k=k
                    # No language filtering - search all documents
                )
                
                if results:
                    logger.debug(f"Fallback search successful: {len(results)} results from all languages")
                    return results
                    
            except Exception as e:
                logger.warning(f"Fallback search failed: {e}")
        
        logger.warning(f"All search strategies failed for query: '{query[:50]}...'")
        return []
    
    async def get_available_languages(self) -> List[str]:
        """Get list of available languages in the vector store."""
        self._update_language_stats()
        return list(self.language_stats.keys()) if self.language_stats else []
    
    def is_language_available(self, language: str) -> bool:
        """Check if documents are available in a specific language."""
        return self.language_stats and language in self.language_stats and self.language_stats[language] > 0
    
    def get_language_distribution(self) -> dict:
        """Get the current language distribution statistics."""
        self._update_language_stats()
        return self.language_stats.copy() if self.language_stats else {}

# Convenience functions for language detection
def detect_query_language_simple(query: str) -> str:
    """Simple language detection function that returns just the language code."""
    if not query or not query.strip():
        return 'unknown'
    
    # Count Arabic vs English characters
    arabic_chars = len(re.findall(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]', query))
    english_chars = len(re.findall(r'[A-Za-z]', query))
    
    total_chars = arabic_chars + english_chars
    if total_chars == 0:
        return 'unknown'
    
    arabic_percentage = arabic_chars / total_chars
    
    return 'ar' if arabic_percentage > 0.5 else 'en'

def is_arabic_query(query: str) -> bool:
    """Quick check if a query contains Arabic text."""
    if not query:
        return False
    arabic_pattern = r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]'
    return bool(re.search(arabic_pattern, query))

def is_english_query(query: str) -> bool:
    """Quick check if a query is primarily English."""
    if not query:
        return False
    english_chars = len(re.findall(r'[A-Za-z]', query))
    total_chars = len(re.sub(r'[^\w\s]', '', query))
    
    return total_chars > 0 and (english_chars / total_chars) > 0.5 