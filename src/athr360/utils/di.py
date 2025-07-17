"""
Dependency-provider helpers for FastAPI.

Each object is created lazily once per process and can be overridden
in tests with FastAPI's dependency-override mechanism.

Optimized for permissive-first RAG approach with comprehensive knowledge base coverage.
"""

from functools import lru_cache

from athr360.services.gemini_service import GeminiService
from athr360.services.intent_service import IntentDetectionService
from athr360.services.content_classification_service import ContentClassificationService
from athr360.services.message_service import MessageService
from athr360.infrastructure.vector_store import VectorStore
from athr360.core.rag.engine import RAG 
from athr360.core.adapters.llm_gemini import LLMServiceAdapter


@lru_cache
def get_llm() -> GeminiService:
    """Return a shared GeminiService instance."""
    return GeminiService()


@lru_cache
def get_intent_service() -> IntentDetectionService:
    """
    Return a shared IntentDetectionService for conversation flow control.
    
    This service handles CONVERSATION MANAGEMENT INTENT:
    - Determines when users want to CONTINUE vs END conversations
    - Used after "Is there anything else I can help you with?" questions
    - Prevents false positives like "cool, what about X?" ending sessions
    
    Note: This is separate from RESPONSE TONE INTENT which is integrated 
    into the prompt system for determining empathetic vs neutral responses.
    """
    return IntentDetectionService(llm_service=get_llm())


@lru_cache
def get_content_classification_service() -> ContentClassificationService:
    """
    Return a shared ContentClassificationService for intelligent conversation flow analysis.
    
    This service determines:
    - When conversations should end and feedback should be collected
    - Appropriate response strategies for different content types
    - Safety interventions and policy violations
    - Smart redirection for off-topic queries
    
    Uses LLM analysis instead of hardcoded keywords for better accuracy.
    """
    return ContentClassificationService(llm_service=get_llm())


@lru_cache
def get_message_service() -> MessageService:
    """
    Return a shared MessageService instance for database operations.
    
    This service handles:
    - Storing user and bot messages in the database
    - Message threading and reply relationships
    - Session and conversation tracking
    - Message analytics and reporting
    """
    return MessageService()


@lru_cache
def get_vector_store() -> VectorStore:
    """Return a shared VectorStore instance with comprehensive document coverage."""
    return VectorStore()


@lru_cache
def get_rag() -> RAG:
    """
    Return a shared RAG pipeline instance optimized for permissive-first approach.
    
    This configuration:
    - Always uses the vector store for retrieval
    - Applies intent-aware ranking for better results  
    - Provides graceful degradation for comprehensive coverage
    - Includes integrated response tone detection in prompts
    """
    return RAG(
        vector_store=get_vector_store(),
        llm_provider=LLMServiceAdapter(get_llm()),
        top_k=12,  # Increased for better knowledge base coverage
    )
