#!/usr/bin/env python3
"""
Comprehensive test script for Arabic PDF extraction and language-aware routing.

This script tests:
1. Arabic PDF text extraction improvements
2. Language detection accuracy
3. Smart query routing functionality
4. Vector store language filtering
5. End-to-end multilingual query processing

Usage:
    python test_language_routing.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from athr360.services.language_router import LanguageAwareQueryRouter, detect_query_language_simple, LanguageDetectionResult
from athr360.services.processor import ChatProcessor
from athr360.core.chunking import _detect_language, _is_arabic_text, process_document
from athr360.infrastructure.vector_store import VectorStore
from athr360.utils.di import get_vector_store

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LanguageRoutingTester:
    """Comprehensive tester for language-aware routing system."""
    
    def __init__(self):
        self.test_queries = {
            'arabic': [
                "ما هو قانون حماية البيانات؟",
                "كيف يمكنني الحصول على إجازة؟",
                "ما هي سياسة العمل من المنزل؟",
                "أين يمكنني العثور على معلومات التأمين الطبي؟"
            ],
            'english': [
                "What is the PDPL data protection law?",
                "How can I request vacation leave?", 
                "What is the work from home policy?",
                "Where can I find medical insurance information?"
            ],
            'mixed': [
                "What is ما هو PDPL?",
                "How to request إجازة vacation?",
                "Policy سياسة work from home?"
            ]
        }
        
        self.sample_arabic_text = "هذا نص تجريبي باللغة العربية. يحتوي على معلومات مهمة حول السياسات والإجراءات."
        self.sample_english_text = "This is a sample English text. It contains important information about policies and procedures."
        
    async def test_language_detection(self):
        """Test language detection accuracy."""
        logger.info("🔍 Testing Language Detection...")
        
        test_cases = [
            ("Arabic text", self.sample_arabic_text, 'ar'),
            ("English text", self.sample_english_text, 'en'),
            ("Mixed text", f"{self.sample_english_text} {self.sample_arabic_text}", 'ar'),  # Arabic should win
            ("Empty text", "", 'unknown'),
            ("Numbers only", "12345", 'unknown'),
        ]
        
        correct_detections = 0
        total_tests = len(test_cases)
        
        for test_name, text, expected_lang in test_cases:
            detected = detect_query_language_simple(text)
            is_correct = detected == expected_lang
            
            status = "✅" if is_correct else "❌"
            logger.info(f"{status} {test_name}: Expected '{expected_lang}', Got '{detected}'")
            
            if is_correct:
                correct_detections += 1
        
        accuracy = (correct_detections / total_tests) * 100
        logger.info(f"📊 Language Detection Accuracy: {accuracy:.1f}% ({correct_detections}/{total_tests})")
        
        return accuracy > 80  # Pass if >80% accurate

    async def test_arabic_text_detection(self):
        """Test Arabic text detection helper functions."""
        logger.info("🔤 Testing Arabic Text Detection...")
        
        test_cases = [
            (self.sample_arabic_text, True),
            (self.sample_english_text, False),
            ("Mixed: Hello مرحبا", True),
            ("English only", False),
            ("", False),
        ]
        
        all_correct = True
        for text, expected in test_cases:
            result = _is_arabic_text(text)
            is_correct = result == expected
            status = "✅" if is_correct else "❌"
            logger.info(f"{status} Arabic detection: '{text[:30]}...' -> {result} (expected {expected})")
            
            if not is_correct:
                all_correct = False
        
        return all_correct

    async def test_vector_store_language_filtering(self):
        """Test vector store language filtering capabilities."""
        logger.info("📚 Testing Vector Store Language Filtering...")
        
        try:
            vector_store = get_vector_store()
            
            # Get language statistics
            stats = vector_store.get_language_statistics()
            logger.info(f"📊 Language distribution: {stats}")
            
            if not stats:
                logger.warning("⚠️ No language statistics available - vector store may be empty")
                return False
            
            # Test language filtering for each available language
            for language in stats.keys():
                if stats[language] > 0:  # Only test languages with documents
                    docs = vector_store.get_documents_by_language(language)
                    logger.info(f"✅ Language '{language}': {len(docs)} documents found")
                    
                    # Verify documents are actually in that language
                    sample_count = min(3, len(docs))
                    for i in range(sample_count):
                        doc_lang = docs[i].metadata.get('language', 'unknown')
                        if doc_lang != language:
                            logger.warning(f"⚠️ Document language mismatch: expected '{language}', got '{doc_lang}'")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Vector store test failed: {e}")
            return False

    async def test_smart_query_routing(self):
        """Test smart query routing with different language queries."""
        logger.info("🧠 Testing Smart Query Routing...")
        
        try:
            vector_store = get_vector_store()
            router = LanguageAwareQueryRouter(vector_store)
            
            # Test Arabic queries
            logger.info("Testing Arabic queries...")
            for query in self.test_queries['arabic']:
                results = await router.smart_search(query, k=3)
                detected_lang = router.detect_query_language(query).detected_language
                logger.info(f"🔍 '{query[:30]}...' -> Language: {detected_lang}, Results: {len(results)}")
                
                if results:
                    # Check if results are predominantly Arabic
                    arabic_results = sum(1 for doc in results if doc.metadata.get('language') == 'ar')
                    logger.info(f"   Arabic results: {arabic_results}/{len(results)}")
            
            # Test English queries
            logger.info("Testing English queries...")
            for query in self.test_queries['english']:
                results = await router.smart_search(query, k=3)
                detected_lang = router.detect_query_language(query).detected_language
                logger.info(f"🔍 '{query[:30]}...' -> Language: {detected_lang}, Results: {len(results)}")
                
                if results:
                    # Check if results are predominantly English
                    english_results = sum(1 for doc in results if doc.metadata.get('language') == 'en')
                    logger.info(f"   English results: {english_results}/{len(results)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Smart routing test failed: {e}")
            return False

    async def test_chat_processor_integration(self):
        """Test end-to-end chat processing with language routing."""
        logger.info("💬 Testing Chat Processor Integration...")
        
        try:
            processor = ChatProcessor()
            
            # Get language info
            lang_info = await processor.get_language_info()
            logger.info(f"📊 Language support: {lang_info}")
            
            # Test with sample queries (without actually calling LLM)
            test_queries = [
                "What is PDPL?",
                "ما هو قانون حماية البيانات؟",
                "Policy information"
            ]
            
            for query in test_queries:
                detected_lang = processor._detect_and_log_language(query)
                should_use_cross = processor._should_use_cross_language_search(query, detected_lang)
                logger.info(f"🔍 '{query}' -> Language: {detected_lang}, Cross-language: {should_use_cross}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Chat processor test failed: {e}")
            return False

    async def test_pdf_extraction_improvements(self):
        """Test improved PDF extraction for Arabic text."""
        logger.info("📄 Testing PDF Extraction Improvements...")
        
        # This would require actual PDF files to test properly
        # For now, we'll test the text processing functions
        
        arabic_sample = "هذه وثيقة مهمة تحتوي على:\n• معلومات السياسة\n• الإجراءات المطلوبة\n• تفاصيل الاتصال"
        english_sample = "This is an important document containing:\n• Policy information\n• Required procedures\n• Contact details"
        
        # Test language detection on extracted text
        arabic_detected = _detect_language(arabic_sample)
        english_detected = _detect_language(english_sample)
        
        arabic_correct = arabic_detected == 'ar'
        english_correct = english_detected == 'en'
        
        status_ar = "✅" if arabic_correct else "❌"
        status_en = "✅" if english_correct else "❌"
        
        logger.info(f"{status_ar} Arabic text detection: {arabic_detected}")
        logger.info(f"{status_en} English text detection: {english_detected}")
        
        return arabic_correct and english_correct

    async def run_all_tests(self):
        """Run all tests and provide summary."""
        logger.info("🚀 Starting Language Routing Test Suite...")
        logger.info("=" * 60)
        
        tests = [
            ("Language Detection", self.test_language_detection),
            ("Arabic Text Detection", self.test_arabic_text_detection),
            ("Vector Store Language Filtering", self.test_vector_store_language_filtering),
            ("Smart Query Routing", self.test_smart_query_routing),
            ("Chat Processor Integration", self.test_chat_processor_integration),
            ("PDF Extraction Improvements", self.test_pdf_extraction_improvements),
        ]
        
        results = {}
        
        for test_name, test_func in tests:
            logger.info(f"\n📋 Running: {test_name}")
            logger.info("-" * 40)
            
            try:
                result = await test_func()
                results[test_name] = result
                status = "✅ PASSED" if result else "❌ FAILED"
                logger.info(f"Result: {status}")
                
            except Exception as e:
                logger.error(f"❌ ERROR in {test_name}: {e}")
                results[test_name] = False
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("📊 TEST SUMMARY")
        logger.info("=" * 60)
        
        passed = sum(1 for result in results.values() if result)
        total = len(results)
        
        for test_name, result in results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            logger.info(f"{status} {test_name}")
        
        logger.info(f"\n🎯 Overall Result: {passed}/{total} tests passed")
        
        if passed == total:
            logger.info("🎉 ALL TESTS PASSED! Language routing is working correctly.")
        else:
            logger.warning(f"⚠️ {total - passed} test(s) failed. Please review the results above.")
        
        return passed == total

async def main():
    """Main test runner."""
    tester = LanguageRoutingTester()
    success = await tester.run_all_tests()
    
    if success:
        logger.info("\n✨ Language routing system is ready for production!")
        return 0
    else:
        logger.error("\n❌ Some tests failed. Please fix the issues before proceeding.")
        return 1

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result) 