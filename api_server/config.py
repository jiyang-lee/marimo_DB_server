import os
from datetime import timedelta, timezone


LLM_SERVER_URL = os.getenv("LLM_SERVER_URL", "http://llm-server:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_TIMEZONE = "Asia/Seoul"
KST = timezone(timedelta(hours=9), name="KST")
REALTIME_RETENTION_DAYS = 7
REALTIME_CLEANUP_INTERVAL_SECONDS = 7 * 24 * 60 * 60
SESSION_HISTORY_LIMIT = 16
