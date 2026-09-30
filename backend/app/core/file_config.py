from __future__ import annotations

from enum import Enum


class FileType(str, Enum):
    PDF = "pdf"


# The extraction pipeline only supports PDFs for now, so uploads are
# restricted to PDF as well.
ALLOWED_EXTENSIONS: set[str] = {
    ".pdf",
}

# MIME types (optional second check)
ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
}

MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 MB
