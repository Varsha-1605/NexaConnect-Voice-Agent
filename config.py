import os

from dotenv import load_dotenv

load_dotenv()

# environment settings
# test worker sets AGENT_NAME=nexaconnect-ashley-test
AGENT_NAME = os.environ.get("AGENT_NAME", "nexaconnect-ashley")

# LiveKit Cloud runs on UTC
BUSINESS_TIMEZONE = os.environ.get("BUSINESS_TIMEZONE", "America/New_York")

# Pinecone namespace: production (deployed) or test
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "nexaconnect-kb")
PINECONE_NAMESPACE = os.environ.get("PINECONE_NAMESPACE", "production")

# call limits
# hard cap on call length
MAX_CALL_SECONDS = 20 * 60

# silence before "Are you still there?", then hang up
CUSTOMER_SILENCE_TIMEOUT = 10.0
STILL_THERE_WAIT = 3.0

# slower lookups get a spoken line
FILLER_DELAY = 1.2

# turn taking
# min wait after the customer stops talking
ENDPOINT_MIN_DELAY = 0.4
ENDPOINT_MAX_DELAY = 0.5
ENDPOINT_ALPHA = 0.5
INTERRUPTION_MIN_DURATION = 0.5
FALSE_INTERRUPTION_TIMEOUT = 1.0

# voice models
STT_MODEL = "deepgram/nova-3"
STT_BACKUP_MODEL = "assemblyai/universal-streaming"
STT_LANGUAGE = "en"

TTS_MODEL = "cartesia/sonic-3"
TTS_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
TTS_LANGUAGE = "en"
TTS_BACKUP_MODEL = "deepgram/aura-2"
TTS_BACKUP_VOICE = "athena"

PRIMARY_LLM = "google/gemma-4-31b-it"
# direct to OpenAI, covers a LiveKit Inference outage
BACKUP_LLM = "gpt-4.1-mini"

# startup
# max wait for the index lookup in prewarm
PREWARM_KB_TIMEOUT = 5.0

# database
# max 2 parallel lookups per call
DB_POOL_MIN = 1
DB_POOL_MAX = 2
DB_QUERY_TIMEOUT = 5
DB_CONNECT_TIMEOUT = 5
DB_IDLE_CONNECTION_SECONDS = 60
# one retry after a dropped connection
DB_READ_RETRY_DELAY = 0.2

# knowledge base
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# chunks per search
SEARCH_RESULTS = 3

# Pinecone drops idle connections
# a tiny query keeps it open
KEEPALIVE_INTERVAL = 4.0

# slower search = knowledge base unavailable
SEARCH_TIMEOUT = 4.0

# ingest
INGEST_FILE_TYPES = ("*.md", "*.txt")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
UPLOAD_BATCH = 100
UPLOAD_ATTEMPTS = 3

# customer verification
# attempts per call
MAX_VERIFICATION_ATTEMPTS = 3
# failed attempts per address before lockout
MAX_FAILED_VERIFICATIONS = 5
LOCKOUT_HOURS = 24

# business rules
# max days ahead for installation
MAX_INSTALLATION_DAYS_AHEAD = 60
# days of dates listed in the date line
UPCOMING_DAYS = 28



