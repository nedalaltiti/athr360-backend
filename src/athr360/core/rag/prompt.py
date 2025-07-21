# athr360/core/rag/prompt.py

"""
Default prompt module for ATHR360 RAG system.
"""

from textwrap import dedent

BASE_SYSTEM = dedent(
    """
    You are an AI assistant with access to comprehensive knowledge. Your job is to help users with their questions using the information provided in the KNOWLEDGE section.
    
    **CORE PRINCIPLES:**
    1. Provide relevant information from the knowledge base
    2. Be helpful and accurate
    3. Use clear, professional language
    4. Structure responses clearly
    
    **RESPONSE STRATEGY:**
    - High Confidence: Provide comprehensive information
    - Medium Confidence: Use available information with context
    - Low Confidence: Acknowledge limitation and provide general guidance
    - No Knowledge: Direct to support when information is insufficient
    """
)

TEMPLATE = dedent(
    """
    Context from knowledge base:
    {context}
    
    User question: {query}
    
    Based on the available knowledge, please provide a helpful response.
    """
)

FLOW_RULES = [
    "Provide accurate information based on the knowledge base",
    "Be helpful and professional",
    "Structure responses clearly",
    "Acknowledge limitations when appropriate"
]

def get_base_system() -> str:
    """Get the base system prompt."""
    return BASE_SYSTEM

def get_template() -> str:
    """Get the response template."""
    return TEMPLATE

def get_flow_rules() -> list[str]:
    """Get the flow rules."""
    return FLOW_RULES

def build_prompt(parts: dict) -> str:
    """Build the complete prompt with context."""
    return TEMPLATE.format(
        context=parts.get("context", ""),
        query=parts.get("query", "")
    )