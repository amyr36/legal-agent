#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
legal_similarity.py
====================

مقایسه شباهت معنایی بین دو سند حقوقی فارسی، با احترام به ساختار سلسله‌مراتبی
متن (باب / فصل / ماده).

مراحل کار:
  ۱. خواندن دو فایل متنی (txt)
  ۲. نرمال‌سازی متن (یکسان‌سازی حروف عربی/فارسی، حذف کاراکترهای نامرئی و...)
  ۳. تشخیص سرتیترهای «باب»، «فصل» و «ماده» با regex و چانک‌کردن متن بر همان اساس
  ۴. برداری‌سازی (embedding) هر چانک با مدل چندزبانه
     paraphrase-multilingual-MiniLM-L12-v2 از sentence-transformers
  ۵. محاسبه شباهت کسینوسی بین همه چانک‌های سند اول و سند دوم
  ۶. خروجی JSON شامل فقط جفت‌چانک‌هایی که شباهت‌شان بالاتر از یک آستانه است

نصب پیش‌نیازها:
    pip install sentence-transformers

اجرا:
    python legal_similarity.py doc1.txt doc2.txt \
        --threshold 0.75 \
        --output result.json
"""

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# ۱. نرمال‌سازی متن
# ---------------------------------------------------------------------------

# نگاشت کاراکترهای عربی به معادل فارسی رایج در متون حقوقی ایران
_AR_TO_FA = {
    "\u064A": "\u06CC",  # ي -> ی
    "\u0643": "\u06A9",  # ك -> ک
    "\u0629": "\u0647",  # ة -> ه
    "\u0649": "\u06CC",  # ى -> ی
}

# اعداد عربی/انگلیسی به فارسی (برای یکسان‌سازی نمایش، نه محاسبه)
_DIGITS_TO_FA = {
    "0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴",
    "5": "۵", "6": "۶", "7": "۷", "8": "۸", "9": "۹",
}

_ZERO_WIDTH_CHARS = ["\u200c", "\u200d", "\u200e", "\u200f", "\ufeff"]


def normalize_text(text: str) -> str:
    """یکسان‌سازی حروف عربی/فارسی، حذف کاراکترهای نامرئی و فاصله‌های اضافی."""
    text = unicodedata.normalize("NFC", text)
    for ar, fa in _AR_TO_FA.items():
        text = text.replace(ar, fa)
    for zw in _ZERO_WIDTH_CHARS:
        text = text.replace(zw, " ")
    # حذف اعراب عربی احتمالی (فتحه، کسره، ضمه، تشدید و ...)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    # یکسان‌سازی فاصله‌ها
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def digits_to_fa(s: str) -> str:
    return "".join(_DIGITS_TO_FA.get(ch, ch) for ch in s)


# ---------------------------------------------------------------------------
# ۲. تشخیص سرتیترهای باب / فصل / ماده
# ---------------------------------------------------------------------------

# اعداد ترتیبی نوشتاری رایج در متون حقوقی فارسی (تا حد کافی برای بیشتر اسناد)
_ORDINAL_WORDS = (
    r"اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
    r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|هفدهم|هجدهم|نوزدهم|بیستم"
)

# شماره به صورت رقم (فارسی یا انگلیسی) یا کلمه‌ی ترتیبی
_NUMBER_PART = rf"(?:[0-9۰-۹]+|{_ORDINAL_WORDS})"

HEADER_PATTERNS = {
    # ترتیب اهمیت: باب > فصل > ماده
    "bab": re.compile(rf"^\s*باب\s+({_NUMBER_PART})\s*[:\-–—]?\s*(.*)$"),
    "fasl": re.compile(rf"^\s*فصل\s+({_NUMBER_PART})\s*[:\-–—]?\s*(.*)$"),
    "madeh": re.compile(rf"^\s*ماده\s*[یيی]?\s*({_NUMBER_PART})\s*[:\-–—]?\s*(.*)$"),
}


@dataclass
class Chunk:
    chunk_id: str
    doc_name: str
    bab: Optional[str] = None
    fasl: Optional[str] = None
    madeh: Optional[str] = None
    text: str = ""
    lines: List[str] = field(default_factory=list)

    def finalize(self) -> None:
        self.text = normalize_text("\n".join(self.lines))

    def label(self) -> str:
        parts = []
        if self.bab:
            parts.append(f"باب {self.bab}")
        if self.fasl:
            parts.append(f"فصل {self.fasl}")
        if self.madeh:
            parts.append(f"ماده {self.madeh}")
        return " / ".join(parts) if parts else "(بدون سرتیتر)"


def chunk_legal_text(raw_text: str, doc_name: str) -> List[Chunk]:
    """
    متن را بر اساس سرتیترهای باب/فصل/ماده به چانک تقسیم می‌کند.
    هر چانک جدید با دیدن یک سرتیتر (باب، فصل یا ماده) شروع می‌شود؛
    باب و فصل به عنوان «زمینه» برای ماده‌های بعدی نگه داشته می‌شوند.
    """
    text = normalize_text(raw_text)
    lines = text.split("\n")

    chunks: List[Chunk] = []
    current_bab: Optional[str] = None
    current_fasl: Optional[str] = None
    current: Optional[Chunk] = None
    counter = 0

    def flush():
        nonlocal current
        if current is not None and any(l.strip() for l in current.lines):
            current.finalize()
            chunks.append(current)
        current = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current is not None:
                current.lines.append(line)
            continue

        m_bab = HEADER_PATTERNS["bab"].match(stripped)
        m_fasl = HEADER_PATTERNS["fasl"].match(stripped)
        m_madeh = HEADER_PATTERNS["madeh"].match(stripped)

        if m_bab:
            flush()
            current_bab = digits_to_fa(m_bab.group(1))
            current_fasl = None
            counter += 1
            current = Chunk(
                chunk_id=f"{doc_name}#{counter}",
                doc_name=doc_name,
                bab=current_bab,
                fasl=current_fasl,
            )
            current.lines.append(line)
        elif m_fasl:
            flush()
            current_fasl = digits_to_fa(m_fasl.group(1))
            counter += 1
            current = Chunk(
                chunk_id=f"{doc_name}#{counter}",
                doc_name=doc_name,
                bab=current_bab,
                fasl=current_fasl,
            )
            current.lines.append(line)
        elif m_madeh:
            flush()
            madeh_num = digits_to_fa(m_madeh.group(1))
            counter += 1
            current = Chunk(
                chunk_id=f"{doc_name}#{counter}",
                doc_name=doc_name,
                bab=current_bab,
                fasl=current_fasl,
                madeh=madeh_num,
            )
            current.lines.append(line)
        else:
            if current is None:
                counter += 1
                current = Chunk(
                    chunk_id=f"{doc_name}#{counter}",
                    doc_name=doc_name,
                    bab=current_bab,
                    fasl=current_fasl,
                )
            current.lines.append(line)

    flush()
    # حذف چانک‌های خالی احتمالی
    return [c for c in chunks if c.text.strip()]


# ---------------------------------------------------------------------------
# ۳. برداری‌سازی و محاسبه شباهت
# ---------------------------------------------------------------------------

def embed_chunks(chunks: List[Chunk], model_name: str):
    """چانک‌ها را با مدل sentence-transformers به بردار تبدیل می‌کند."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit(
            "کتابخانه‌ی sentence-transformers نصب نیست.\n"
            "با دستور زیر آن را نصب کنید:\n"
            "    pip install sentence-transformers"
        )

    model = SentenceTransformer(model_name)
    texts = [c.text for c in chunks]
    embeddings = model.encode(
        texts,
        convert_to_tensor=True,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return embeddings


def compute_similarity_pairs(
    chunks1: List[Chunk],
    emb1,
    chunks2: List[Chunk],
    emb2,
    threshold: float,
):
    """شباهت کسینوسی بین همه‌ی جفت‌چانک‌های دو سند را محاسبه می‌کند
    و فقط جفت‌هایی که شباهت‌شان >= threshold است را برمی‌گرداند."""
    from sentence_transformers import util

    sim_matrix = util.cos_sim(emb1, emb2)  # shape: (len1, len2)

    results = []
    for i, c1 in enumerate(chunks1):
        for j, c2 in enumerate(chunks2):
            score = float(sim_matrix[i][j])
            if score >= threshold:
                results.append(
                    {
                        "similarity": round(score, 4),
                        "doc1": {
                            "chunk_id": c1.chunk_id,
                            "bab": c1.bab,
                            "fasl": c1.fasl,
                            "madeh": c1.madeh,
                            "label": c1.label(),
                            "text": c1.text,
                        },
                        "doc2": {
                            "chunk_id": c2.chunk_id,
                            "bab": c2.bab,
                            "fasl": c2.fasl,
                            "madeh": c2.madeh,
                            "label": c2.label(),
                            "text": c2.text,
                        },
                    }
                )

    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# ۴. اجرای اصلی
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="مقایسه شباهت معنایی بین دو سند حقوقی فارسی بر اساس چانک‌های باب/فصل/ماده."
    )
    parser.add_argument("doc1", type=str, help="مسیر فایل متنی سند اول")
    parser.add_argument("doc2", type=str, help="مسیر فایل متنی سند دوم")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="آستانه شباهت کسینوسی برای درج در خروجی (پیش‌فرض: 0.75)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="paraphrase-multilingual-MiniLM-L12-v2",
        help="نام مدل sentence-transformers برای embedding",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="similarity_result.json",
        help="مسیر فایل خروجی JSON",
    )
    args = parser.parse_args()

    doc1_path = Path(args.doc1)
    doc2_path = Path(args.doc2)

    if not doc1_path.exists():
        sys.exit(f"فایل یافت نشد: {doc1_path}")
    if not doc2_path.exists():
        sys.exit(f"فایل یافت نشد: {doc2_path}")

    raw1 = doc1_path.read_text(encoding="utf-8")
    raw2 = doc2_path.read_text(encoding="utf-8")

    print("در حال چانک‌کردن سند اول...")
    chunks1 = chunk_legal_text(raw1, doc_name=doc1_path.stem)
    print(f"  -> {len(chunks1)} چانک استخراج شد.")

    print("در حال چانک‌کردن سند دوم...")
    chunks2 = chunk_legal_text(raw2, doc_name=doc2_path.stem)
    print(f"  -> {len(chunks2)} چانک استخراج شد.")

    if not chunks1 or not chunks2:
        sys.exit("هیچ چانکی از یکی از اسناد استخراج نشد. الگوی باب/فصل/ماده را بررسی کنید.")

    print(f"در حال بارگذاری مدل: {args.model}")
    emb1 = embed_chunks(chunks1, args.model)
    emb2 = embed_chunks(chunks2, args.model)

    print("در حال محاسبه شباهت‌ها...")
    pairs = compute_similarity_pairs(chunks1, emb1, chunks2, emb2, args.threshold)

    output = {
        "doc1": doc1_path.name,
        "doc2": doc2_path.name,
        "model": args.model,
        "threshold": args.threshold,
        "num_chunks_doc1": len(chunks1),
        "num_chunks_doc2": len(chunks2),
        "num_matches": len(pairs),
        "matches": pairs,
    }

    out_path = Path(args.output)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nانجام شد. {len(pairs)} جفت‌چانک با شباهت >= {args.threshold} یافت شد.")
    print(f"خروجی در فایل ذخیره شد: {out_path.resolve()}")


if __name__ == "__main__":
    main()