"""Single source of truth for all constants, paths and schemas of the project.

Runnable standalone:  python -m core.config
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# core/config.py  →  core/  →  project_root/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
RESULTS_PATH = os.path.join(BASE_DIR, "analysis_results.jsonl")

DOCUMENT_SLOTS = {
    "A": {
        "context_path": os.path.join(SOURCES_DIR, "context_A.jsonl"),
        "temp_dir": os.path.join(SOURCES_DIR, "temp", "document_A"),
    },
    "B": {
        "context_path": os.path.join(SOURCES_DIR, "context_B.jsonl"),
        "temp_dir": os.path.join(SOURCES_DIR, "temp", "document_B"),
    },
}

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "ai_models/sentence-transformer-parsbert-fa-2.0"

# ---------------------------------------------------------------------------
# Record schema
# ---------------------------------------------------------------------------

METADATA_FIELDS = [
    "id",
    "law_seq",
    "category",
    "law",
    "book",
    "chapter",
    "subchapter",
    "type",
    "number_raw",
    "number",
    "parent_number",
    "breadcrumb",
]

# internal-only key added to Document.metadata so we can recover the record index
RECORD_INDEX_KEY = "_record_index"

# ---------------------------------------------------------------------------
# Retrieval / LLM tunables
# ---------------------------------------------------------------------------

TOP_K = 3
LLM_BATCH_SIZE = 6
LLM_MAX_RETRIES = 2
MAX_CONCURRENT_REQUESTS = 20

# ---------------------------------------------------------------------------
# Chat model config
# ---------------------------------------------------------------------------

CHAT_MODEL_BASE_URL = "https://api.avalai.ir/v1"
CHAT_MODEL_API_KEY = "aa-2UNRjqu93VzHsPv8qTZX7gn4QqBhXtUwyBak1UHFbky7i08T"
CHAT_MODEL_NAME = "deepseek-v4-flash"
EFFORT = "high"

# ---------------------------------------------------------------------------
# Legal relation taxonomy
# ---------------------------------------------------------------------------

RELATION_VALUES = ["مشابه", "متناقض", "بی‌ارتباط"]

RELATION_TYPE_VALUES = [
    "تکرار مقرراتی", "اقتباس", "تکمیل", "تخصیص", "تعارض",
    "نسخ صریح", "نسخ ضمنی", "ابهام تفسیری", "ناسازگاری اصلاحی",
    "هم‌ارزی حکمی", "سایر",
]


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== core.config ===")
    print(f"BASE_DIR        = {BASE_DIR}")
    print(f"SOURCES_DIR     = {SOURCES_DIR}")
    print(f"RESULTS_PATH    = {RESULTS_PATH}")
    print(f"EMBEDDING_MODEL = {EMBEDDING_MODEL}")
    print(f"CHAT_MODEL      = {CHAT_MODEL_NAME} @ {CHAT_MODEL_BASE_URL}")
    print(f"TOP_K           = {TOP_K}")
    print(f"LLM_BATCH_SIZE  = {LLM_BATCH_SIZE}")
    print("DOCUMENT_SLOTS:")
    for k, slot in DOCUMENT_SLOTS.items():
        print(f"  {k}: context={slot['context_path']}")
        print(f"     temp={slot['temp_dir']}")
    print(f"METADATA_FIELDS = {METADATA_FIELDS}")
    print(f"relation types  = {RELATION_TYPE_VALUES}")