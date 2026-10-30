"""All settings and tunable numbers in one place.

Two kinds of values:
- Settings that change per environment (test vs production) are read from environment variables,
  with a default. Secrets (API keys, DATABASE_URL, phone numbers) stay in .env and are not here.
- Everything else is a plain constant: change it here and it applies everywhere.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------- environment settings
# The deployed agent is "nexaconnect-ashley". The test worker sets AGENT_NAME=nexaconnect-ashley-test,
# so tests never take real customers' calls.
AGENT_NAME = os.environ.get("AGENT_NAME", "nexaconnect-ashley")

# LiveKit Cloud runs on UTC, so dates are worked out in this time zone instead.
BUSINESS_TIMEZONE = os.environ.get("BUSINESS_TIMEZONE", "America/New_York")

# Pinecone index, and the namespace inside it: "production" for the deployed agent, "test" for the
# test worker and CI.
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "nexaconnect-kb")
PINECONE_NAMESPACE = os.environ.get("PINECONE_NAMESPACE", "production")

# ---------------------------------------------------------------- call limits
# Hard limit on call length; limits abuse and how long a deploy has to wait for calls to finish.
MAX_CALL_SECONDS = 20 * 60

# After this many seconds of customer silence (the agent's own speech doesn't count) the agent asks
# "Are you still there?", then ends the call if the customer still hasn't spoken this long after it.
CUSTOMER_SILENCE_TIMEOUT = 10.0
STILL_THERE_WAIT = 3.0

# A lookup that finishes within this time stays silent; a slower one gets a spoken line.
FILLER_DELAY = 1.2

# ---------------------------------------------------------------- turn taking
# Wait at least this long after the customer stops talking before replying. Too low splits one
# sentence into two turns when speech-to-text is slow.
ENDPOINT_MIN_DELAY = 0.4
ENDPOINT_MAX_DELAY = 0.5
ENDPOINT_ALPHA = 0.5
INTERRUPTION_MIN_DURATION = 0.5
FALSE_INTERRUPTION_TIMEOUT = 1.0

# ---------------------------------------------------------------- voice models (primary and backup)
STT_MODEL = "deepgram/nova-3"
STT_BACKUP_MODEL = "assemblyai/universal-streaming"
STT_LANGUAGE = "en"

TTS_MODEL = "cartesia/sonic-3"
TTS_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
TTS_LANGUAGE = "en"
TTS_BACKUP_MODEL = "deepgram/aura-2"
TTS_BACKUP_VOICE = "athena"

PRIMARY_LLM = "google/gemma-4-31b-it"
# Direct to OpenAI (not through LiveKit Inference), so it also covers an Inference outage.
BACKUP_LLM = "gpt-4.1-mini"

# ---------------------------------------------------------------- startup
# How long prewarm waits for the Pinecone index lookup before it is finished at call start instead.
PREWARM_KB_TIMEOUT = 5.0

# ---------------------------------------------------------------- database
# Two parallel lookups is the most any tool runs. Each call has its own pool, so this keeps total
# connections at 2 per call through Neon's pooler.
DB_POOL_MIN = 1
DB_POOL_MAX = 2
DB_QUERY_TIMEOUT = 5
DB_CONNECT_TIMEOUT = 5
DB_IDLE_CONNECTION_SECONDS = 60
# A read that fails on a dropped connection is retried once after this many seconds.
DB_READ_RETRY_DELAY = 0.2

# ---------------------------------------------------------------- knowledge base
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Chunks returned for each search.
SEARCH_RESULTS = 3

# Pinecone drops an idle connection after a few seconds and reconnecting costs 1-2.5 s.
# A tiny query this often keeps it open during a call.
KEEPALIVE_INTERVAL = 4.0

# Embedding + search slower than this is treated as "knowledge base not available".
# Normal searches take well under 1 s near us-east-1; 4 s leaves room for a cold connection.
# The agent already speaks a waiting line while it searches.
SEARCH_TIMEOUT = 4.0

# Ingest (kb/ingest.py)
INGEST_FILE_TYPES = ("*.md", "*.txt")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
UPLOAD_BATCH = 100
UPLOAD_ATTEMPTS = 3

# ---------------------------------------------------------------- customer verification
# Attempts within one call before the agent stops trying.
MAX_VERIFICATION_ATTEMPTS = 3
# Failed verifications for one address across all calls before it is locked, and for how long.
MAX_FAILED_VERIFICATIONS = 5
LOCKOUT_HOURS = 24

# ---------------------------------------------------------------- business rules
# Installation can be booked at most this many days ahead.
MAX_INSTALLATION_DAYS_AHEAD = 60
# Days of upcoming dates listed to the model in the date line.
UPCOMING_DAYS = 28
