import os
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
COLLECTION = "chunks"
MAX_PAGES = 500
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
