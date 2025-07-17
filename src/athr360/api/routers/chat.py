"""
General chat API router for any frontend interface.

This module provides a simple, universal chat API that can be used by:
- Web frontends
- Mobile apps
- Desktop applications
- Custom integrations

Features:
- Regular chat responses
- Streaming responses
- Session management
- Message persistence
- CORS-friendly
"""

import asyncio
import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from athr360.schemas.models import ChatRequest, ChatResponse, ChatStreamChunk
from athr360.services.processor import ChatProcessor
from athr360.services.session_tracker import SessionTracker
from athr360.services.message_service import MessageService
from athr360.services.content_classification_service import ContentClassificationService
from athr360.utils.di import get_content_classification_service, get_message_service
from athr360.utils.bot_name import get_bot_name

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize services
chat_processor = ChatProcessor()
session_tracker = SessionTracker(idle_minutes=30)  # 30 minutes for web sessions


async def _safe_save_message(message_service, **kwargs):
    """Safely save a message to the database, handling connection errors."""
    try:
        await message_service.add_message(**kwargs)
    except Exception as e:
        logger.warning(f"Database not available, skipping message save: {e}")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Process a chat message and return a response.
    
    This endpoint provides a simple, universal chat interface that can be used
    by any frontend application.
    """
    start_time = time.time()
    
    try:
        # Validate request
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Get or create session
        session_id = request.session_id or session_tracker.get(request.user_id)
        
        # Get message service
        message_service = get_message_service()
        
        # Get conversation context
        from athr360.services.session_tracker import get_or_create_memory
        memory = await get_or_create_memory(request.user_id)
        
        # Analyze conversation flow
        classification_service = get_content_classification_service()
        conversation_context = None
        if memory.messages:
            recent_messages = memory.messages[-4:]
            conversation_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_messages])
        
        analysis = await classification_service.analyze_conversation_flow(
            user_message=request.message,
            conversation_context=conversation_context,
            response_type="standard"
        )
        
        # Save user message (skip if database not available)
        user_msg_id = None
        try:
            user_msg_id = await message_service.add_message(
                bot_name=get_bot_name(),
                env="production",
                channel="chat_api",
                user_id=request.user_id,
                session_id=session_id,
                role="user",
                text=request.message,
                intent=None,
                reply_to_id=None,
            )
        except Exception as e:
            logger.warning(f"Database not available, skipping message save: {e}")
            user_msg_id = 1  # Dummy ID for continuation
        
        # Process message with chat processor
        result = await chat_processor.process_message(
            request.message,
            chat_history=[m["content"] for m in memory.messages],
            user_id=request.user_id
        )
        
        processing_time = time.time() - start_time
        
        if result.is_success():
            response_data = result.unwrap()
            bot_response = response_data["response"].strip()
            
            # Update memory
            memory.add_user_message(request.message)
            memory.add_ai_message(bot_response)
            
            # Save bot response (skip if database not available)
            intent = classification_service.get_message_intent(analysis)
            if user_msg_id:  # Only save if we have a valid user message ID
                background_tasks.add_task(
                    _safe_save_message,
                    message_service=message_service,
                    bot_name=get_bot_name(),
                    env="production",
                    channel="chat_api",
                    user_id=request.user_id,
                    session_id=session_id,
                    role="bot",
                    text=bot_response,
                    intent=intent,
                    reply_to_id=user_msg_id,
                )
            
            # Process confidence level
            confidence = response_data.get("confidence_level", 0.0)
            if isinstance(confidence, str):
                confidence_map = {"high": 0.9, "medium": 0.7, "low": 0.5, "very_low": 0.3}
                confidence = confidence_map.get(confidence, 0.5)
            
            # Process sources to extract just the titles
            sources = response_data.get("sources", [])
            if sources and isinstance(sources[0], dict):
                sources = [source.get("title", str(source)) for source in sources]
            
            return ChatResponse(
                response=bot_response,
                session_id=session_id,
                processing_time=round(processing_time, 2),
                confidence=confidence,
                sources=sources
            )
        else:
            # Error handling
            error_response = "I apologize, but I encountered an error processing your request. Please try again."
            
            # Update memory with error
            memory.add_user_message(request.message)
            memory.add_ai_message(error_response)
            
            # Save error response (skip if database not available)
            if user_msg_id:  # Only save if we have a valid user message ID
                background_tasks.add_task(
                    _safe_save_message,
                    message_service=message_service,
                    bot_name=get_bot_name(),
                    env="production",
                    channel="chat_api",
                    user_id=request.user_id,
                    session_id=session_id,
                    role="bot",
                    text=error_response,
                    intent="error",
                    reply_to_id=user_msg_id,
                )
            
            return ChatResponse(
                response=error_response,
                session_id=session_id,
                processing_time=round(processing_time, 2),
                confidence=0.0,
                sources=[]
            )
            
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Process a chat message and return a streaming response.
    
    This endpoint provides real-time streaming responses for a better user experience.
    """
    try:
        # Validate request
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Get or create session
        session_id = request.session_id or session_tracker.get(request.user_id)
        
        # Get message service
        message_service = get_message_service()
        
        # Get conversation context
        from athr360.services.session_tracker import get_or_create_memory
        memory = await get_or_create_memory(request.user_id)
        
        # Analyze conversation flow
        classification_service = get_content_classification_service()
        conversation_context = None
        if memory.messages:
            recent_messages = memory.messages[-4:]
            conversation_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_messages])
        
        analysis = await classification_service.analyze_conversation_flow(
            user_message=request.message,
            conversation_context=conversation_context,
            response_type="standard"
        )
        
        # Save user message (skip if database not available)
        user_msg_id = None
        try:
            user_msg_id = await message_service.add_message(
                bot_name=get_bot_name(),
                env="production",
                channel="chat_api",
                user_id=request.user_id,
                session_id=session_id,
                role="user",
                text=request.message,
                intent=None,
                reply_to_id=None,
            )
        except Exception as e:
            logger.warning(f"Database not available, skipping message save: {e}")
            user_msg_id = 1  # Dummy ID for continuation
        
        async def stream_generator() -> AsyncGenerator[str, None]:
            """Generator for streaming chat responses."""
            full_response = ""
            
            try:
                # Stream from chat processor
                async for chunk in chat_processor.process_message_streaming(
                    request.message,
                    chat_history=[m["content"] for m in memory.messages[:-1]],
                    user_id=request.user_id
                ):
                    full_response += chunk
                    
                    # Create streaming chunk
                    chunk_data = ChatStreamChunk(
                        content=chunk,
                        session_id=session_id,
                        is_final=False
                    )
                    
                    yield f"data: {chunk_data.model_dump_json()}\n\n"
                    
                    # Small delay to prevent overwhelming the client
                    await asyncio.sleep(0.01)
                
                # Send final chunk
                final_chunk = ChatStreamChunk(
                    content="",
                    session_id=session_id,
                    is_final=True
                )
                yield f"data: {final_chunk.model_dump_json()}\n\n"
                
                # Update memory and save response
                if full_response.strip():
                    memory.add_user_message(request.message)
                    memory.add_ai_message(full_response)
                    
                    # Save bot response (skip if database not available)
                    intent = classification_service.get_message_intent(analysis)
                    if user_msg_id:  # Only save if we have a valid user message ID
                        background_tasks.add_task(
                            _safe_save_message,
                            message_service=message_service,
                            bot_name=get_bot_name(),
                            env="production",
                            channel="chat_api",
                            user_id=request.user_id,
                            session_id=session_id,
                            role="bot",
                            text=full_response,
                            intent=intent,
                            reply_to_id=user_msg_id,
                        )
                    
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                error_chunk = ChatStreamChunk(
                    content="I apologize, but I encountered an error. Please try again.",
                    session_id=session_id,
                    is_final=True
                )
                yield f"data: {error_chunk.model_dump_json()}\n\n"
        
        return StreamingResponse(
            stream_generator(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )
        
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in chat streaming endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chat/session/{user_id}")
async def get_session_info(user_id: str):
    """
    Get session information for a user.
    
    Returns the current session ID and basic session status.
    """
    try:
        session_id = session_tracker.get(user_id)
        
        return {
            "user_id": user_id,
            "session_id": session_id,
            "active": session_id is not None
        }
        
    except Exception as e:
        logger.error(f"Error getting session info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/chat/session/{user_id}")
async def clear_session(user_id: str):
    """
    Clear/reset a user's session.
    
    This will start a fresh conversation context for the user.
    """
    try:
        # Clear session tracker
        session_tracker.clear(user_id)
        
        # Clear memory
        from athr360.services.session_tracker import clear_memory
        clear_memory(user_id)
        
        return {
            "message": "Session cleared successfully",
            "user_id": user_id
        }
        
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") 