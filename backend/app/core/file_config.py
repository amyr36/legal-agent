from __future__ import annotations

from enum import Enum


class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    TXT = "txt"
    MD = "md"
    RTF = "rtf"


ALLOWED_EXTENSIONS: set[str] = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".md",
    ".rtf",
}

# MIME types (optional second check)
ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/rtf",
    "text/rtf",
}

MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 MB