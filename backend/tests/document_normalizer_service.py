from __future__ import annotations

import re


_DIGIT_TABLE = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class TextNormalizer:

    @staticmethod
    def normalize(text: str) -> str:

        if not text:
            return ""

        text = TextNormalizer._normalize_newlines(
            text
        )

        text = TextNormalizer._normalize_letters(
            text
        )

        text = TextNormalizer._normalize_digits(
            text
        )

        text = TextNormalizer._remove_diacritics(
            text
        )

        text = TextNormalizer._remove_control_chars(
            text
        )

        text = TextNormalizer._normalize_spaces(
            text
        )

        return text.strip()

    @staticmethod
    def _normalize_newlines(
        text: str,
    ) -> str:

        text = text.replace(
            "\r\n",
            "\n",
        )

        text = text.replace(
            "\r",
            "\n",
        )

        return text

    @staticmethod
    def _normalize_letters(
        text: str,
    ) -> str:

        replacements = {
            "ي": "ی",
            "ى": "ی",
            "ك": "ک",
            "ـ": "",
        }

        for old, new in replacements.items():
            text = text.replace(
                old,
                new,
            )

        return text

    @staticmethod
    def _normalize_digits(
        text: str,
    ) -> str:

        return text.translate(
            _DIGIT_TABLE
        )

    @staticmethod
    def _remove_diacritics(
        text: str,
    ) -> str:

        return re.sub(
            r"[\u064B-\u065F\u0670]",
            "",
            text,
        )

    @staticmethod
    def _remove_control_chars(
        text: str,
    ) -> str:

        return re.sub(
            r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]",
            "",
            text,
        )

    @staticmethod
    def _normalize_spaces(
        text: str,
    ) -> str:

        text = re.sub(
            r"[ \t]+",
            " ",
            text,
        )

        text = "\n".join(
            line.strip()
            for line in text.splitlines()
        )

        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        return text