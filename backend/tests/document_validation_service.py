from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from app.core.file_config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
)


class FileValidator:

    @staticmethod
    async def validate(file: UploadFile) -> None:

        FileValidator._validate_extension(
            file.filename
        )

        FileValidator._validate_content_type(
            file.content_type
        )

        await FileValidator._validate_size(
            file
        )

    @staticmethod
    def _validate_extension(
        filename: str | None,
    ) -> None:

        if not filename:
            raise ValueError(
                "Filename is missing"
            )

        extension = (
            Path(filename)
            .suffix
            .lower()
        )

        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {extension}"
            )

    @staticmethod
    def _validate_content_type(
        content_type: str | None,
    ) -> None:

        if content_type not in ALLOWED_MIME_TYPES:
            raise ValueError(
                f"Unsupported MIME type: {content_type}"
            )

    @staticmethod
    async def _validate_size(
        file: UploadFile,
    ) -> None:

        content = await file.read()

        size = len(content)

        await file.seek(0)

        if size > MAX_FILE_SIZE:
            raise ValueError(
                "File size exceeds limit"
            )