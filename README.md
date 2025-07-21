# ATHAR360 AI Compliance Assistant

Unified AI compliance assistant powered by Google Gemini AI and RAG (Retrieval-Augmented Generation) technology for Personal Data Protection Law (PDPL) compliance.

## 🌟 Features

- **Unified Multilingual System**: Single instance handles both Arabic and English documents
- **Automatic Language Detection**: Responds in the same language as the user's query
- **Intelligent RAG**: Context-aware responses using comprehensive PDPL knowledge base
- **Real-time Streaming**: Fast, responsive conversations with streaming responses
- **32 PDPL Documents**: Comprehensive coverage of both Arabic and English PDPL regulations
- **3,299 Document Chunks**: Processed and embedded for semantic search
- **Production Ready**: Comprehensive deployment and monitoring solutions

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud project with Vertex AI enabled
- 4GB+ RAM available

### 1. Setup Environment

```bash
# Clone the repository
git clone <repository-url>
cd athr360-backend

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
export PYTHONPATH=src
export APP_INSTANCE=compliance
export SKIP_DB_INIT=true
```

### 2. Load Embeddings

```bash
# Load embeddings for all documents
./load_embeddings.sh

# Or manually:
python scripts/load_embeddings.py compliance
```

### 3. Start the Server

```bash
# Start the server
./start_server.sh

# Or manually:
PYTHONPATH=src APP_INSTANCE=compliance SKIP_DB_INIT=true python -m uvicorn athr360.api.app:app --host 0.0.0.0 --port 8000
```

### 4. Test the System

**English Query:**
```bash
curl -X POST "http://localhost:8000/api/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is PDPL?", "user_id": "test"}'
```

**Arabic Query:**
```bash
curl -X POST "http://localhost:8000/api/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"message": "ما هو قانون حماية البيانات الشخصية؟", "user_id": "test"}'
```

## 📁 Project Structure

```
athr360-backend/
├── src/athr360/                # Application source code
│   ├── api/                   # FastAPI routers and endpoints
│   ├── core/                  # RAG engine and document processing
│   ├── infrastructure/        # External service adapters
│   ├── services/              # Business logic services
│   └── utils/                 # Utility functions
├── data/                      # Instance-specific data
│   ├── knowledge/             # Knowledge base documents               
│   │   └── compliance/        # compliance documents
│   ├── embeddings/            # Vector embeddings
│   └── prompts/               # LLM prompts
├── scripts/                   # Deployment and utility scripts
├── docker/                    # Docker configuration
├── docker-compose.yml        # Unified deployment configuration
└── instances.yaml            # App instance definitions
```

## ⚙️ Configuration

### Environment Variables

```bash
# Application Configuration
APP_INSTANCE=compliance
PYTHONPATH=src
SKIP_DB_INIT=true

# Google Cloud Configuration  
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# Performance Settings
ENABLE_STREAMING=true
CACHE_EMBEDDINGS=true
```

### Knowledge Base

The system uses a unified knowledge base containing:
- **16 Arabic PDPL documents** (automatically detected)
- **16 English PDPL documents** (automatically detected)
- **32 total documents** processed into 3,299 searchable chunks

## 🔧 How Language Detection Works

### 1. **Automatic Content Analysis**
- Unicode character range analysis (`\u0600-\u06FF` for Arabic)
- Percentage-based language determination (60% threshold)
- Metadata enrichment for each document chunk

### 2. **Query Processing**
- User query language detection
- Semantic search across all documents
- Language-matched response generation

### 3. **Response Generation**
- **Arabic queries** → Arabic responses using Arabic documents
- **English queries** → English responses using English documents
- Single unified prompt with dynamic language switching

## 🎯 API Endpoints

### Chat Stream
```
POST /api/chat/stream
Content-Type: application/json

{
  "message": "Your question here",
  "user_id": "user_identifier"
}
```

**Response:** Server-sent events with streaming content

## 📊 Performance

- **Embedding Model**: Google Vertex AI `text-embedding-005`
- **Vector Dimensions**: 768
- **Search Strategy**: Multi-strategy semantic search
- **Response Time**: < 3 seconds for most queries
- **Concurrent Users**: Supports multiple simultaneous queries

## 🛠️ Development

### Add New Documents
1. Place documents in `data/knowledge/compliance/`
2. Run `./load_embeddings.sh` to process new documents
3. Restart server to use updated embeddings

### Modify Prompts
1. Edit `data/prompts/compliance/prompt.py`
2. Restart server to apply changes

## 🔍 Troubleshooting

### Common Issues

1. **Server won't start**: Check that `APP_INSTANCE=compliance` is set
2. **No responses**: Ensure embeddings are loaded with `./load_embeddings.sh`
3. **Wrong language**: Verify document language detection in logs
4. **Module not found**: Set `PYTHONPATH=src` before running

### Logs

The system provides detailed logging:
- Instance detection and configuration
- Document processing and language detection
- Query processing and response generation
- Performance metrics and debugging info

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

**ATHAR360 AI Compliance Assistant** - Unified multilingual compliance support powered by advanced AI.