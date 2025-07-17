# athar360/infrastructure/ingest.py
"""
Auto-ingest helper
──────────────────
Scan app-specific knowledge directory, embed any *new* files, and persist them.

• Skips files that are already present in the VectorStore
  (we compare absolute file paths stored in metadata).
• Returns the number of documents embedded during this run.
"""

from __future__ import annotations

import logging
from pathlib import Path

from athr360.core.chunking import process_document            
from athr360.infrastructure.vector_store import VectorStore
from athr360.config.app_config import get_current_app_config

logger = logging.getLogger(__name__)

async def refresh_vector_index(store: VectorStore) -> int:
    # Get app-specific knowledge directory
    app_config = get_current_app_config()
    knowledge_dir = app_config.knowledge_base_dir
    
    logger.info(f"Refreshing vector index from: {knowledge_dir}")
    
    if not knowledge_dir.exists():
        logger.warning("Knowledge dir %s does not exist", knowledge_dir)
        return 0

    # Get all indexed file paths and normalize them for comparison
    already_indexed = set()
    for doc in store.documents:
        file_path = doc.metadata.get("file_path")
        if file_path:
            # Convert to absolute path for consistent comparison
            if Path(file_path).is_absolute():
                already_indexed.add(file_path)
            else:
                # Convert relative path to absolute
                already_indexed.add(str(Path(file_path).resolve()))

    # Find new files by comparing absolute paths
    new_files = []
    for fp in knowledge_dir.glob("*"):
        if fp.is_file():
            file_abs_path = str(fp.resolve())
            if file_abs_path not in already_indexed:
                new_files.append(fp)

    if not new_files:
        logger.info(f"No new files to index in {knowledge_dir}")
        logger.info(f"Already indexed {len(already_indexed)} files")
        return 0

    logger.info(f"Found {len(new_files)} new files to index:")
    for fp in new_files:
        logger.info(f"  - {fp.name}")

    chunks = []
    for fp in new_files:
        # process_document() already extracts, chunks and fills metadata
        chunks.extend(await process_document(str(fp)))

    if chunks:
        await store.add_documents(chunks)
        logger.info("Embedded %d new docs (%d chunks) for app instance: %s", 
                   len(new_files), len(chunks), app_config.instance_id)

    return len(new_files)