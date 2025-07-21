"""
Unified document-processing & chunking layer for the RAG pipeline with multi-app support
─────────────────────────────────────────────────────────────────
• Advanced text extraction (PDF, DOCX, TXT, etc.)                 – non-blocking
• Configurable, sentence-aware chunking with overlap              – ChunkingConfig
• Rich metadata (hash, word/char count, page numbers, …)
• Async-safe helpers: save_uploaded_file(), reload_knowledge_base(), get_relevant_chunks()
• Multi-app support with app instance-specific knowledge bases
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import base64
import json
import tempfile

import aiofiles  # Add this import for async file operations
import pdfplumber
import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request

from athr360.config.settings import settings
from athr360.config.app_config import get_current_app_config, get_instance_manager
from athr360.core.document import Document
from athr360.infrastructure.vector_store import VectorStore
from athr360.utils.di import get_vector_store  # Import the app-aware version

# Add language detection import at the top of the file
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles  # Add this import for async file operations
import pdfplumber

# Add language detection function
def _detect_language(text: str) -> str:
    """
    Detect language of text content using heuristic approach.
    
    Args:
        text: Input text to analyze
        
    Returns:
        Language code: 'ar' for Arabic, 'en' for English
    """
    if not text or not text.strip():
        return 'unknown'
    
    # Clean text for analysis
    clean_text = re.sub(r'[^\w\s]', '', text).strip()
    
    # Count Arabic characters
    arabic_chars = len(re.findall(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]', clean_text))
    
    # Count English characters
    english_chars = len(re.findall(r'[A-Za-z]', clean_text))
    
    # Total meaningful characters
    total_chars = arabic_chars + english_chars
    
    if total_chars == 0:
        return 'unknown'
    
    # Calculate percentages
    arabic_percentage = arabic_chars / total_chars
    english_percentage = english_chars / total_chars
    
    # Determine language based on majority
    if arabic_percentage > 0.6:
        return 'ar'
    elif english_percentage > 0.6:
        return 'en'
    elif arabic_percentage > english_percentage:
        return 'ar'
    else:
        return 'en'

def _is_arabic_text(text: str) -> bool:
    """Check if text contains Arabic characters."""
    if not text:
        return False
    # More comprehensive Arabic character detection
    arabic_pattern = r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]'
    return bool(re.search(arabic_pattern, text))

def _extract_text_pdf(path: str) -> str:
    """
    Advanced PDF extraction with improved Arabic text handling.
    
    Enhanced for multilingual documents:
    - Proper Arabic/RTL text extraction
    - Preserves text direction and formatting
    - Handles mixed language documents
    """
    with pdfplumber.open(path) as pdf:
        extracted_content = []
        
        for page_num, page in enumerate(pdf.pages, 1):
            page_content = []
            page_content.append(f"=== PAGE {page_num} ===")
            
            # Extract tables first (they contain structured information)
            tables = page.extract_tables()
            if tables:
                page_content.append("\n--- TABLES ---")
                for table_idx, table in enumerate(tables, 1):
                    if table and len(table) > 0:
                        page_content.append(f"\nTable {table_idx}:")
                        # Convert table to structured text
                        formatted_table = _format_table_for_text(table)
                        page_content.append(formatted_table)
            
            # Extract regular text with improved Arabic handling
            try:
                # Try layout-preserved extraction first
                text_content = page.extract_text(layout=True, x_tolerance=3, y_tolerance=3)
                if text_content:
                    # Enhanced text structure that handles Arabic properly
                    structured_text = _enhance_text_structure_multilingual(text_content)
                    if structured_text.strip():
                        page_content.append("\n--- CONTENT ---")
                        page_content.append(structured_text)
                
                # Fallback extraction with different settings for better Arabic support
                if not text_content or len(text_content.strip()) < 50:
                    # Try without layout preservation for corrupted layouts
                    fallback_text = page.extract_text(layout=False, x_tolerance=1, y_tolerance=1)
                    if fallback_text and fallback_text != text_content:
                        additional_content = _extract_additional_content_multilingual(fallback_text, str(page_content))
                        if additional_content:
                            page_content.append("\n--- ADDITIONAL ---")
                            page_content.append(additional_content)
                            
            except Exception as e:
                logger.warning(f"PDF text extraction error on page {page_num}: {e}")
                # Final fallback - try basic extraction
                try:
                    basic_text = page.extract_text()
                    if basic_text:
                        page_content.append("\n--- BASIC EXTRACTION ---")
                        page_content.append(_clean_extracted_text(basic_text))
                except Exception as e2:
                    logger.error(f"All PDF extraction methods failed on page {page_num}: {e2}")
            
            extracted_content.append("\n".join(page_content))
    
    return "\n\n".join(extracted_content)

async def _extract_text_pdf_mistral_ocr(path: str) -> str:
    """
    Extract text from PDF using Mistral OCR API for enhanced Arabic text extraction.
    
    Args:
        path: Path to the PDF file
        
    Returns:
        Extracted text with proper Arabic encoding
    """
    if not settings.mistral_ocr.enabled:
        logger.debug("Mistral OCR is disabled, falling back to standard extraction")
        return _extract_text_pdf(path)
    
    if not settings.mistral_ocr.service_account_json:
        logger.warning("Mistral OCR service account JSON not configured, falling back to standard extraction")
        return _extract_text_pdf(path)
    
    try:
        logger.info(f"Using Mistral OCR for PDF extraction: {path}")
        
        # Create credentials from service account JSON
        service_account_info = json.loads(settings.mistral_ocr.service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        
        # Refresh credentials to get access token
        credentials.refresh(Request())
        
        # Build endpoint URL
        base_url = f"https://{settings.mistral_ocr.region}-aiplatform.googleapis.com/v1"
        endpoint_url = f"{base_url}/projects/{settings.mistral_ocr.project_id}/locations/{settings.mistral_ocr.region}/publishers/mistralai/models/{settings.mistral_ocr.model_name}-{settings.mistral_ocr.model_version}:rawPredict"
        
        # Encode PDF to base64
        with open(path, 'rb') as pdf_file:
            pdf_content = pdf_file.read()
            encoded_pdf = base64.b64encode(pdf_content).decode('utf-8')
        
        # Prepare request
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {credentials.token}"
        }
        
        payload = {
            "model": f"{settings.mistral_ocr.model_name}-{settings.mistral_ocr.model_version}",
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{encoded_pdf}",
            },
        }
        
        # Make OCR request
        logger.debug(f"Making Mistral OCR request to: {endpoint_url}")
        async with httpx.AsyncClient(timeout=settings.mistral_ocr.timeout_seconds) as client:
            response = await client.post(url=endpoint_url, headers=headers, json=payload)
            response.raise_for_status()
            
            if response.status_code == 200:
                ocr_result = response.json()
                
                # Extract text from all pages
                extracted_content = []
                if "pages" in ocr_result:
                    for page_idx, page_data in enumerate(ocr_result["pages"]):
                        page_content = [f"=== PAGE {page_idx + 1} ==="]
                        
                        # Get markdown content if available
                        if "markdown" in page_data:
                            markdown_content = page_data["markdown"].strip()
                            if markdown_content:
                                page_content.append(markdown_content)
                        
                        # Get plain text if available
                        elif "text" in page_data:
                            text_content = page_data["text"].strip()
                            if text_content:
                                page_content.append(text_content)
                        
                        if len(page_content) > 1:  # More than just the page header
                            extracted_content.append("\n".join(page_content))
                
                result_text = "\n\n".join(extracted_content)
                logger.info(f"Mistral OCR extraction successful: {len(result_text)} characters extracted from {len(ocr_result.get('pages', []))} pages")
                return result_text
            else:
                logger.warning(f"Mistral OCR request failed with status {response.status_code}")
                return _extract_text_pdf(path)  # Fallback
                
    except json.JSONDecodeError as e:
        logger.error(f"Invalid service account JSON configuration: {e}")
        return _extract_text_pdf(path)  # Fallback
    except httpx.HTTPError as e:
        logger.error(f"Mistral OCR HTTP error: {e}")
        return _extract_text_pdf(path)  # Fallback
    except Exception as e:
        logger.error(f"Mistral OCR extraction failed: {e}")
        return _extract_text_pdf(path)  # Fallback

def _clean_extracted_text(text: str) -> str:
    """Clean extracted text while preserving Arabic characters."""
    if not text:
        return ""
    
    # Remove excessive whitespace while preserving Arabic spacing
    text = re.sub(r'[ \t]+', ' ', text)  # Replace multiple spaces/tabs with single space
    text = re.sub(r'\n\s*\n', '\n\n', text)  # Replace multiple newlines with double newline
    
    # Fix common PDF extraction issues
    text = re.sub(r'([a-zA-Z])\s+([a-zA-Z])', r'\1\2', text)  # Fix broken English words
    
    # Don't mess with Arabic text spacing as it might break the text
    return text.strip()

def _enhance_text_structure_multilingual(text: str) -> str:
    """
    Enhanced text structure processing that properly handles Arabic and RTL text.
    
    Improvements:
    - Preserves Arabic text formatting
    - Handles RTL text direction
    - Doesn't apply English-specific formatting rules to Arabic text
    """
    if not text:
        return ""
    
    lines = text.split('\n')
    enhanced_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check if line contains Arabic text
        has_arabic = _is_arabic_text(line)
        
        if has_arabic:
            # For Arabic text, minimal processing to preserve original formatting
            enhanced_lines.append(line)
        else:
            # Apply English text enhancements
            # Detect and enhance list items
            if re.match(r'^[•·▪▫‣⁃]\s*', line):
                # Already a bullet point
                enhanced_lines.append(line)
            elif re.match(r'^\d+\.\s+', line):
                # Numbered list
                enhanced_lines.append(line)
            elif re.match(r'^[a-zA-Z]\.\s+', line):
                # Lettered list
                enhanced_lines.append(line)
            elif re.match(r'^-\s+', line):
                # Dash list - convert to bullet
                enhanced_lines.append(line.replace('-', '•', 1))
            else:
                # Regular text processing for English content
                if len(line) < 200 and ':' in line and not line.endswith('.'):
                    # Might be a definition or category
                    enhanced_lines.append(line)
                elif re.match(r'^[A-Z][^.!?]*[^.!?]\s*$', line) and len(line) < 100:
                    # Might be a heading or category (all caps, no sentence ending)
                    enhanced_lines.append(f"**{line}**")
                else:
                    enhanced_lines.append(line)
    
    return '\n'.join(enhanced_lines)

def _extract_additional_content_multilingual(fallback_text: str, existing_content: str) -> str:
    """Extract additional content with multilingual support."""
    if not fallback_text:
        return ""
    
    # For Arabic text, use different sentence splitting
    if _is_arabic_text(fallback_text):
        # Arabic sentence splitting - be more conservative
        sentences = re.split(r'[.!?؟۔]\s+', fallback_text)
    else:
        # English sentence splitting
        sentences = re.split(r'[.!?]+', fallback_text)
    
    new_content = []
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 10 and sentence not in existing_content:
            # Check if it looks like meaningful content
            if _is_arabic_text(sentence):
                # For Arabic, add if it's substantial content
                if len(sentence) > 20:
                    new_content.append(sentence)
            else:
                # English content filtering
                if re.search(r'\b(policy|procedure|benefit|discount|employee|contact|phone|email|address)\b', sentence.lower()):
                    new_content.append(sentence)
    
    return '. '.join(new_content) + '.' if new_content else ""

logger = logging.getLogger(__name__)

class ChunkingConfig:
    def __init__(
        self,
        chunk_size: int = 1_000,
        chunk_overlap: int = 200,
        ensure_complete_sentences: bool = True,
        max_characters_per_doc: int = 1_000_000,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.ensure_complete_sentences = ensure_complete_sentences
        self.max_characters_per_doc = max_characters_per_doc

    @classmethod
    def from_settings(cls) -> "ChunkingConfig":
        return cls(
            chunk_size=settings.performance.chunk_size,
            chunk_overlap=settings.performance.chunk_overlap,
            ensure_complete_sentences=True,  # Always ensure complete sentences for readability
        )

async def _run_blocking(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _format_table_for_text(table: List[List[str]]) -> str:
    """Convert extracted table to well-formatted text that preserves structure."""
    if not table or len(table) == 0:
        return ""
    
    formatted_rows = []
    
    # Process header row if it exists
    if len(table) > 0 and table[0]:
        header = table[0]
        # Clean and format header
        clean_header = [str(cell or "").strip() for cell in header]
        if any(clean_header):  # Only add if header has content
            formatted_rows.append("| " + " | ".join(clean_header) + " |")
            # Add separator for markdown-style formatting
            formatted_rows.append("|" + "|".join([" --- " for _ in clean_header]) + "|")
    
    # Process data rows
    for row in table[1:] if len(table) > 1 else table:
        if row:
            clean_row = [str(cell or "").strip() for cell in row]
            if any(clean_row):  # Only add rows with content
                formatted_rows.append("| " + " | ".join(clean_row) + " |")
    
    return "\n".join(formatted_rows)


def _extract_text_docx(path: str) -> str:
    import zipfile
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    parts: list[str] = []

    with zipfile.ZipFile(path) as z:
        def _grab(xml_bytes: bytes):
            root = ET.fromstring(xml_bytes)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            for par in root.findall(f".//{ns}p"):
                texts = "".join(t.text or "" for t in par.findall(f".//{ns}t"))
                if texts:
                    parts.append(texts)

        _grab(z.read("word/document.xml"))

        for item in z.namelist():
            if item.startswith("word/") and item.endswith(".xml") and item != "word/document.xml":
                try:
                    _grab(z.read(item))
                except Exception:
                    # skip bad part
                    pass

    cleaned = re.sub(r"\n+", "\n\n", "\n".join(parts))
    return cleaned


async def _extract_text_txt_async(path: str) -> str:
    """Async text file extraction for better concurrency."""
    try:
        async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
            return await f.read()
    except UnicodeDecodeError:
        async with aiofiles.open(path, mode='r', encoding='latin-1') as f:
            return await f.read()


def _extract_text_txt(path: str) -> str:
    """Sync fallback for text extraction."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, encoding="latin-1") as f:
            return f.read()

async def _extract_text_pdf_router(path: str) -> str:
    """
    Route PDF extraction to Mistral OCR or standard extraction based on configuration.
    
    Args:
        path: Path to the PDF file
        
    Returns:
        Extracted text using the best available method
    """
    if settings.mistral_ocr.enabled and settings.mistral_ocr.service_account_json:
        # Use Mistral OCR for better Arabic support
        return await _extract_text_pdf_mistral_ocr(path)
    else:
        # Use standard pdfplumber extraction
        return _extract_text_pdf(path)

# Updated EXTRACTORS with async support and Mistral OCR for Arabic PDF extraction
EXTRACTORS = {
    ".pdf": _extract_text_pdf_router,  # Smart routing: Mistral OCR or standard extraction
    ".docx": _extract_text_docx,
    ".txt": _extract_text_txt_async,  # Now async!
    ".md": _extract_text_txt_async,   # Now async!
    ".csv": _extract_text_txt_async,  # Now async!
}

ASYNC_EXTRACTORS = {
    ".txt", ".md", ".csv", ".pdf"  # These support async extraction
}

SUPPORTED_EXT = set(EXTRACTORS.keys())  # For backward compatibility

async def process_document(path: str, cfg: ChunkingConfig | None = None) -> List[Document]:
    """
    Process document with optimized async text extraction when possible.
    
    Uses async I/O for text files and optimized blocking for binary formats.
    """
    cfg = cfg or ChunkingConfig.from_settings()
    p = Path(path)
    if not p.exists():
        logger.warning("File not found: %s", path)
        return []

    ext = p.suffix.lower()
    if ext not in EXTRACTORS:
        logger.warning("Unsupported file type: %s", ext)
        return []

    # Use async extraction for supported formats, blocking for others
    if ext in ASYNC_EXTRACTORS:
        text: str = await EXTRACTORS[ext](str(p))
    else:
        # Use thread executor for blocking operations (PDF, DOCX)
        text: str = await _run_blocking(EXTRACTORS[ext], str(p))
        
    if not text:
        logger.warning("No text extracted from %s", p.name)
        return []

    if len(text) > cfg.max_characters_per_doc:
        text = text[: cfg.max_characters_per_doc]

    # Use faster hashing for large documents
    doc_hash = hashlib.md5(text.encode()).hexdigest()
    
    # Detect document language
    detected_language = _detect_language(text)
    
    # Determine language from file path if available
    path_language = None
    if '/english/' in str(p) or '/en/' in str(p):
        path_language = 'en'
    elif '/arabic/' in str(p) or '/ar/' in str(p):
        path_language = 'ar'
    
    # Use path-based language if available, otherwise use detected language
    final_language = path_language or detected_language
    
    meta_base: Dict[str, Any] = {
        "source": p.name,
        "file_path": str(p),
        "file_type": ext,
        "processed_at": datetime.utcnow().isoformat(),
        "doc_hash": doc_hash,
        "char_count": len(text),
        "word_count": len(text.split()),
        "language": final_language,
        "detected_language": detected_language,
        "path_language": path_language,
    }

    chunks = _chunk(text, meta_base, cfg)
    logger.info("Processed %s (%d chars) → %d chunks", p.name, len(text), len(chunks))
    return chunks


def _chunk(text: str, meta: Dict[str, Any], cfg: ChunkingConfig) -> List[Document]:
    """
    Intelligent context-aware chunking that preserves related information.
    
    Follows AI/ML best practices:
    - Structure-aware splitting (preserves tables, lists, sections)
    - Semantic coherence (keeps related content together)
    - Adaptive overlap (more overlap for structured content)
    - Metadata enrichment (chunk type, structure info)
    """
    if not text or not text.strip():
        return []

    # Clean text while preserving structure
    text = re.sub(r' +', ' ', text).strip()
    
    # First, identify document structure
    structured_sections = _identify_document_structure(text)
    
    chunks: list[Document] = []
    
    for section in structured_sections:
        section_chunks = _chunk_section(
            section, 
            meta, 
            cfg.chunk_size, 
            cfg.chunk_overlap, 
            cfg.ensure_complete_sentences
        )
        chunks.extend(section_chunks)
    
    # Add chunk metadata
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        chunk.metadata.update({
            "chunk": i,
            "total_chunks": total,
            "chunk_strategy": "context_aware"
        })
    
    return chunks

def _identify_document_structure(text: str) -> List[Dict[str, Any]]:
    """Identify and categorize different sections of the document."""
    sections = []
    lines = text.split('\n')
    current_section = {
        "content": [],
        "type": "text",
        "priority": "normal"
    }
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Detect tables
        if '|' in line and line.count('|') >= 2:
            # Found a table - collect all table rows
            if current_section["content"]:
                sections.append(current_section)
            
            table_content = []
            while i < len(lines) and ('|' in lines[i] or lines[i].strip() == ''):
                if lines[i].strip():
                    table_content.append(lines[i])
                i += 1
            
            sections.append({
                "content": table_content,
                "type": "table", 
                "priority": "high"  # Tables often contain important structured info
            })
            
            current_section = {"content": [], "type": "text", "priority": "normal"}
            continue
        
        # Detect lists (multiple consecutive list items)
        elif re.match(r'^[•·▪▫‣⁃\-\*]\s+', line) or re.match(r'^\d+\.\s+', line):
            # Found a list - collect related list items
            if current_section["content"] and current_section["type"] != "list":
                sections.append(current_section)
            
            if current_section["type"] != "list":
                current_section = {"content": [], "type": "list", "priority": "high"}
            
            current_section["content"].append(line)
            
        # Detect section headers (PAGE markers, etc.)
        elif re.match(r'^===.*===$', line) or re.match(r'^---.*---$', line):
            if current_section["content"]:
                sections.append(current_section)
            
            sections.append({
                "content": [line],
                "type": "header",
                "priority": "low"
            })
            
            current_section = {"content": [], "type": "text", "priority": "normal"}
            
        # Regular content
        else:
            if line:  # Skip empty lines
                current_section["content"].append(line)
        
        i += 1
    
    # Add final section if it has content
    if current_section["content"]:
        sections.append(current_section)
    
    return sections

def _chunk_section(section: Dict[str, Any], meta: Dict[str, Any], 
                  chunk_size: int, overlap: int, ensure_sentences: bool) -> List[Document]:
    """Chunk a section based on its type and content."""
    content_lines = section["content"]
    section_type = section["type"]
    priority = section["priority"]
    
    if not content_lines:
        return []

    section_text = '\n'.join(content_lines)
    
    # Adjust chunking strategy based on section type
    if section_type == "table":
        # Tables should generally stay together as they're structured data
        return [Document(
            page_content=section_text,
            metadata={
                **meta,
                "section_type": "table",
                "priority": priority,
                "preserve_structure": True
            }
        )]
    
    elif section_type == "list":
        # Lists should be kept together if possible, but can be split intelligently
        if len(section_text) <= chunk_size * 1.5:  # Allow slightly larger chunks for lists
            return [Document(
                page_content=section_text,
                metadata={
                    **meta,
                    "section_type": "list", 
                    "priority": priority,
                    "preserve_structure": True
                }
            )]
        else:
            # Split long lists, but try to keep related items together
            return _split_list_intelligently(content_lines, meta, chunk_size, overlap)
    
    elif section_type == "header":
        # Headers are usually short and can be combined with following content
        return [Document(
            page_content=section_text,
            metadata={
                **meta,
                "section_type": "header",
                "priority": priority
            }
        )]
    
    else:  # Regular text
        return _chunk_text_intelligently(section_text, meta, chunk_size, overlap, ensure_sentences)

def _split_list_intelligently(list_lines: List[str], meta: Dict[str, Any], 
                            chunk_size: int, overlap: int) -> List[Document]:
    """Split long lists while keeping related items together."""
    chunks = []
    current_chunk_lines = []
    current_length = 0
    
    for line in list_lines:
        line_length = len(line)
        
        # If adding this line would exceed chunk size, create a chunk
        if current_length + line_length > chunk_size and current_chunk_lines:
            chunk_content = '\n'.join(current_chunk_lines)
            chunks.append(Document(
                page_content=chunk_content,
                metadata={
                    **meta,
                    "section_type": "list_part",
                    "priority": "high"
                }
            ))
            
            # Start new chunk with overlap
            overlap_lines = current_chunk_lines[-2:] if len(current_chunk_lines) > 2 else current_chunk_lines
            current_chunk_lines = overlap_lines + [line]
            current_length = sum(len(l) for l in current_chunk_lines)
        else:
            current_chunk_lines.append(line)
            current_length += line_length
    
    # Add final chunk
    if current_chunk_lines:
        chunk_content = '\n'.join(current_chunk_lines)
        chunks.append(Document(
            page_content=chunk_content,
            metadata={
                **meta,
                "section_type": "list_part",
                "priority": "high"
            }
        ))
    
    return chunks

def _chunk_text_intelligently(text: str, meta: Dict[str, Any], 
                            chunk_size: int, overlap: int, ensure_sentences: bool) -> List[Document]:
    """Chunk regular text with intelligent boundaries."""
    if len(text) <= chunk_size:
        return [Document(
            page_content=text,
            metadata={
                **meta,
                "section_type": "text",
                "priority": "normal"
            }
        )]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = min(start + chunk_size, len(text))
        
        # Try to find a good breaking point
        if ensure_sentences and end < len(text):
            # Look for sentence boundaries
            sentence_ends = [m.end() for m in re.finditer(r'[.!?]+\s+', text[start:end + 100])]
            if sentence_ends:
                # Filter sentence ends that are within the current chunk
                valid_sentence_ends = [s for s in sentence_ends if s <= (end - start)]
                if valid_sentence_ends:
                    best_end = start + max(valid_sentence_ends)
                    if best_end > start + (chunk_size * 0.7):  # Don't make chunks too small
                        end = best_end
        
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(Document(
                page_content=chunk_text,
                metadata={
                    **meta,
                    "section_type": "text",
                    "priority": "normal"
                }
            ))
        
        start = end - overlap if end - overlap > start else end
    
    return chunks

async def get_relevant_chunks(query: str, top_k: int = 5) -> List[Document]:
    store = get_vector_store()
    return await store.similarity_search(query, top_k=top_k)

async def save_uploaded_file(file, app_instance: str = None) -> str:
    """
    Save uploaded file to app instance-specific knowledge base directory using async I/O.
    
    Args:
        file: The uploaded file
        app_instance: Optional app instance name, uses current app if not provided
        
    Returns:
        Path to the saved file
    """
    if app_instance:
        manager = get_instance_manager()
        app_config = manager.get_instance(app_instance)
        if not app_config:
            raise ValueError(f"Invalid app instance: {app_instance}")
    else:
        app_config = get_current_app_config()
    
    knowledge_dir = app_config.knowledge_base_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    dst = knowledge_dir / file.filename
    
    # Use async file writing for better concurrency
    file_content = await file.read()
    async with aiofiles.open(dst, mode='wb') as f:
        await f.write(file_content)
        
    logger.info("Saved file → %s for app instance %s", dst, app_config.name)
    return str(dst)

async def reload_knowledge_base_concurrent(cfg: ChunkingConfig | None = None, concurrency: int = 4, app_instance: str = None) -> int:
    """
    High-performance concurrent knowledge base reloading with optimized I/O.
    
    Args:
        cfg: Chunking configuration
        concurrency: Number of concurrent file processing tasks
        app_instance: Optional app instance name, uses current app if not provided
        
    Returns:
        Number of files processed.
    """
    if app_instance:
        manager = get_instance_manager()
        app_config = manager.get_instance(app_instance)
        if not app_config:
            raise ValueError(f"Invalid app instance: {app_instance}")
    else:
        app_config = get_current_app_config()
    
    knowledge_dir = app_config.knowledge_base_dir
    if not knowledge_dir.exists():
        logger.warning(f"Knowledge base directory does not exist for app instance {app_config.name}: {knowledge_dir}")
        return 0

    store = get_vector_store()
    await store.delete_collection()

    # Get all files and sort by size (process smaller files first for better UI feedback)
    files = [p for p in knowledge_dir.iterdir() if p.is_file()]
    files.sort(key=lambda x: x.stat().st_size)
    
    # Use optimized semaphore for concurrency control
    sem = asyncio.Semaphore(concurrency)
    
    logger.info(f"Reloading knowledge base for app instance {app_config.name} from {knowledge_dir} ({len(files)} files)")

    async def _optimized_worker(p: Path):
        async with sem:
            try:
                return await process_document(str(p), cfg)
            except Exception as e:
                logger.error(f"Error processing {p.name}: {e}")
    return []

    # Process files with progress tracking
    start_time = asyncio.get_event_loop().time()
    
    # Use asyncio.gather for better performance than as_completed for this use case
    chunk_results = await asyncio.gather(*[_optimized_worker(p) for p in files], return_exceptions=True)
    
    # Flatten results and handle exceptions
    all_chunks = []
    successful_files = 0
    for result in chunk_results:
        if isinstance(result, Exception):
            logger.error(f"File processing failed: {result}")
        elif isinstance(result, list):
            all_chunks.extend(result)
            if result:  # Only count as successful if chunks were produced
                successful_files += 1

    if all_chunks:
        await store.add_documents(all_chunks)
    
    processing_time = asyncio.get_event_loop().time() - start_time
    logger.info(f"Completed knowledge base reload for app instance {app_config.name}: {successful_files}/{len(files)} files successful, {len(all_chunks)} chunks in {processing_time:.2f}s")
    return len(files)


# Backward compatibility - calls the optimized version
async def reload_knowledge_base(cfg: ChunkingConfig | None = None, concurrency: int = 4, app_instance: str = None) -> int:
    """
    Backward compatibility wrapper for reload_knowledge_base_concurrent.
    
    This maintains API compatibility while using the optimized implementation.
    """
    return await reload_knowledge_base_concurrent(cfg, concurrency, app_instance)

# Set the DOCX extractor that was missing
EXTRACTORS[".docx"] = _extract_text_docx
