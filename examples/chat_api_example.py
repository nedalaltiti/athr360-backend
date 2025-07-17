#!/usr/bin/env python3
"""
Example script for testing the ATHAR360 Compliance PDPL Chat API endpoints.

This script demonstrates how to use the new chat API endpoints:
- Regular chat (POST /api/chat)
- Streaming chat (POST /api/chat/stream)
- Session management

Run this script to test the ATHAR360 Compliance PDPL Assistant locally.
"""

import asyncio
import aiohttp
import json
import sys
from typing import AsyncGenerator

# API Configuration
API_BASE_URL = "http://localhost:8000"
USER_ID = "test_user_123"

async def test_regular_chat():
    """Test the regular chat endpoint."""
    print("🔥 Testing Regular Chat API")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        # Test message - English (should get English response)
        message = "What are the compliance requirements for remote work in KSA?"
        
        payload = {
            "message": message,
            "user_id": USER_ID,
            "streaming": False
        }
        
        print(f"📤 Sending: {message}")
        
        async with session.post(
            f"{API_BASE_URL}/api/chat",
            json=payload,
            headers={"Content-Type": "application/json"}
        ) as response:
            if response.status == 200:
                result = await response.json()
                print(f"📥 Response: {result['response']}")
                print(f"⏱️  Processing time: {result['processing_time']}s")
                print(f"🎯 Confidence: {result.get('confidence', 'N/A')}")
                print(f"🆔 Session ID: {result['session_id']}")
                if result.get('sources'):
                    print(f"📚 Sources: {result['sources']}")
            else:
                print(f"❌ Error: {response.status} - {await response.text()}")

async def test_streaming_chat():
    """Test the streaming chat endpoint."""
    print("\n🌊 Testing Streaming Chat API")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        # Test message - English (should get English response)
        message = "Tell me about the compliance requirements for companies benefits in KSA"
        
        payload = {
            "message": message,
            "user_id": USER_ID,
            "streaming": True
        }
        
        print(f"📤 Sending: {message}")
        print("📥 Streaming response:")
        
        async with session.post(
            f"{API_BASE_URL}/api/chat/stream",
            json=payload,
            headers={"Content-Type": "application/json"}
        ) as response:
            if response.status == 200:
                full_response = ""
                async for line in response.content:
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith('data: '):
                        data = json.loads(line_str[6:])  # Remove 'data: ' prefix
                        content = data.get('content', '')
                        if content:
                            print(content, end='', flush=True)
                            full_response += content
                        
                        if data.get('is_final', False):
                            print("\n✅ Stream complete!")
                            break
                            
                print(f"\n📝 Full response length: {len(full_response)} characters")
            else:
                print(f"❌ Error: {response.status} - {await response.text()}")

async def test_language_detection():
    """Test dynamic language detection feature."""
    print("\n🌐 Testing Dynamic Language Detection")
    print("=" * 50)
    
    test_messages = [
        ("Hello, what is PDPL?", "English"),
        ("مرحباً، ما هو قانون حماية البيانات الشخصية؟", "Arabic"),
        ("What are the main compliance requirements?", "English"),
        ("كيف يمكنني الحصول على موافقة لمعالجة البيانات؟", "Arabic")
    ]
    
    async with aiohttp.ClientSession() as session:
        for message, expected_lang in test_messages:
            payload = {
                "message": message,
                "user_id": USER_ID,
                "streaming": False
            }
            
            print(f"📤 Sending ({expected_lang}): {message}")
            
            async with session.post(
                f"{API_BASE_URL}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    response_text = result['response']
                    print(f"📥 Response: {response_text[:200]}...")
                    print(f"⏱️  Processing time: {result['processing_time']}s")
                    print(f"🎯 Confidence: {result.get('confidence', 'N/A')}")
                    print()
                else:
                    print(f"❌ Error: {response.status} - {await response.text()}")
                    print()

async def test_session_management():
    """Test session management endpoints."""
    print("\n🔧 Testing Session Management")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        # Get session info
        async with session.get(f"{API_BASE_URL}/api/chat/session/{USER_ID}") as response:
            if response.status == 200:
                session_info = await response.json()
                print(f"📊 Session info: {session_info}")
            else:
                print(f"❌ Error getting session info: {response.status}")
        
        # Clear session
        async with session.delete(f"{API_BASE_URL}/api/chat/session/{USER_ID}") as response:
            if response.status == 200:
                result = await response.json()
                print(f"🗑️  Session cleared: {result}")
            else:
                print(f"❌ Error clearing session: {response.status}")

async def interactive_chat():
    """Interactive chat session for manual testing."""
    print("\n💬 Interactive Chat Session")
    print("=" * 50)
    print("Type your messages below. Type 'quit' to exit, 'clear' to reset session.")
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                user_input = input("\n👤 You: ").strip()
                
                if user_input.lower() == 'quit':
                    print("👋 Goodbye!")
                    break
                elif user_input.lower() == 'clear':
                    async with session.delete(f"{API_BASE_URL}/api/chat/session/{USER_ID}") as response:
                        if response.status == 200:
                            print("🗑️  Session cleared!")
                        else:
                            print("❌ Error clearing session")
                    continue
                elif not user_input:
                    continue
                
                # Send message with streaming
                payload = {
                    "message": user_input,
                    "user_id": USER_ID,
                    "streaming": True
                }
                
                print("🤖 Bot: ", end='', flush=True)
                
                async with session.post(
                    f"{API_BASE_URL}/api/chat/stream",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        async for line in response.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                data = json.loads(line_str[6:])
                                content = data.get('content', '')
                                if content:
                                    print(content, end='', flush=True)
                                
                                if data.get('is_final', False):
                                    print()  # New line after complete response
                                    break
                    else:
                        print(f"❌ Error: {response.status} - {await response.text()}")
                        
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

async def main():
    """Run all tests."""
    print("🚀 ATHAR360 Compliance PDPL API Testing Suite")
    print("=" * 50)
    
    # Check if server is running
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/health/") as response:
                if response.status != 200:
                    print(f"❌ Server not responding. Please start the server first.")
                    print(f"   Run: python -m athr360.api")
                    sys.exit(1)
    except Exception as e:
        print(f"❌ Cannot connect to server at {API_BASE_URL}")
        print(f"   Error: {e}")
        print(f"   Please start the server first: python -m athr360.api")
        sys.exit(1)
    
    print("✅ Server is running!")
    
    # Run tests
    await test_regular_chat()
    await test_streaming_chat()
    await test_language_detection()
    await test_session_management()
    
    # Interactive mode
    print("\n" + "=" * 50)
    response = input("Would you like to try interactive mode? (y/n): ").strip().lower()
    if response in ['y', 'yes']:
        await interactive_chat()

if __name__ == "__main__":
    asyncio.run(main()) 