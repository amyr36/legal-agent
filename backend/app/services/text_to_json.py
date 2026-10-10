"""
Generic legal-text -> JSONL structuring (chunk by structure, LLM per chunk).
Always returns output: if the model/API fails, a rule-based fallback builds
records from the detected structural labels (flagged with `parse_error`).
Not tied to any document template.

Settings (app.core.config.settings): AVALAI_API_KEY, AVALAI_BASE_URL,
AVALAI_MODEL, STRUCTURE_MODEL (all optional; without a key the fallback is used).
"""
import json, logging, re, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings

log = logging.getLogger(__name__)
BASE_URL, MODEL = "https://api.avalai.ir/v1", "deepseek-v4.1-flash"
MAX_CHUNK, WORKERS, ATTEMPTS, TIMEOUT, BACKOFF = 1500, 4, 3, 180, 2.0

# ---------------------------------------------------------------- normalise
_DIG = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUM = r"[0-9۰-۹٠-٩]+"
_N3 = r"[0-9۰-۹٠-٩]{1,3}(?![0-9۰-۹٠-٩])"
_ORD = (r"(?:یک|اول|دو|دوم|سه|سوم|چهار|چهارم|پنج|پنجم|شش|ششم|هفت|هفتم|هشت|هشتم|"
        r"نه|نهم|ده|دهم|" + _NUM + ")")
_ORDV = {"یک": 1, "اول": 1, "دو": 2, "دوم": 2, "سه": 3, "سوم": 3, "چهار": 4, "چهارم": 4,
         "پنج": 5, "پنجم": 5, "شش": 6, "ششم": 6, "هفت": 7, "هفتم": 7, "هشت": 8,
         "هشتم": 8, "نه": 9, "نهم": 9, "ده": 10, "دهم": 10}
_LBL = r"ماده|مادّه|تبصره|بند|جزء|article|clause|note|proviso|subclause|item|paragraph"
_HEAD = r"باب|book|part|فصل|chapter|section|بخش|قسمت|مبحث"
_PL = "\u0622-\u064a\u067e\u0686\u0698\u06a9\u06af\u06cc"
_REV = re.compile(r"[ \t]*-?[ \t]*\)[ \t]*(" + _NUM + r")[ \t]*\([ \t]*")
_WRAP = re.compile(rf"([{_PL}])[ \t]*-[ \t]*\n[ \t]*([{_PL}]+)")
_GLUE = {"ای", "ها", "های", "ی", "تر", "ترین", "ام", "ات", "اش", "مان", "تان", "شان"}


def _fix_paren(line: str) -> str:
    """RTL extraction prints "(5%)" as ") 5 (" with "%" pushed to line end."""
    n = len(_REV.findall(line))
    if not n:
        return line
    if n == 1 and line.rstrip().endswith("%"):
        line = _REV.sub(lambda m: f" ({m[1]}%) ", line).rstrip()[:-1]
    else:
        line = _REV.sub(lambda m: f" ({m[1]}) ", line)
    return re.sub(r" {2,}", " ", line).strip()


_NOTE_END = re.compile(rf"^([ \t]*)({_ORD})[ \t]+(.+?)[ \t]*[-–][ \t]*تبصره[ \t]*$")
_ORPH = re.compile(r"^(?:(.*\S)[ \t]+)?\.([^\s.0-9۰-۹]+)$")


def _fix_lines(lines: list[str]) -> list[str]:
    """RTL-extraction artefacts: «تبصره» pushed to the end of its line (ordinal left at the
    start), and a word displaced behind a period after a dangling hyphen."""
    out = []
    for l in lines:
        n, o = _NOTE_END.match(l), _ORPH.match(l.strip())
        if n:
            out += [f"تبصره {n[2]}", n[3].strip()]
        elif o and out and out[-1].rstrip().endswith("-"):
            out[-1] = out[-1].rstrip()[:-1].rstrip() + " " + o[2] + ("" if o[1] else ".")
            if o[1]:
                out.append(o[1] + ".")
        else:
            out.append(l)
    return out


def normalize_text(text: str) -> str:
    text = text.translate(str.maketrans({"ي": "ی", "ك": "ک"}))
    text = re.sub(r"[\u200f\u200e\u202a-\u202e\ufeff\u0640]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(_fix_lines([_fix_paren(l) for l in text.split("\n")]))
    # a hyphen at a Persian line end is a wrap marker: join (ZWNJ for suffixes)
    text = _WRAP.sub(lambda m: m[1] + ("\u200c" if m[2] in _GLUE else " ") + m[2], text)
    return text.strip()


# ---------------------------------------------------------------- boundaries
_STRUCT = re.compile(
    r"(?mi)^[ \t]*(?:"
    r"(?:ماده|مادّه|article|art\.?)[ \t]*(?:شماره[ \t]*)?[\(\[]?[ \t]*" + _NUM + r"(?!\w)|"
    r"ماده[ \t]*واحده(?!\w)|"
    r"(?:تبصره|note|proviso)(?!\w)(?:[ \t]*[-–:]?[ \t]*" + _ORD + r"(?!\w))?|"
    r"(?:بند|clause|paragraph|جزء|subclause|item)(?!\w)[ \t]*[-–.:]?[ \t]*"
    r"(?:الف|[ا-ی]|[A-Za-z]|" + _NUM + r")(?!\w)|"
    r"(?:" + _HEAD + r")(?!\w)(?:[ \t]*(?:شماره[ \t]*)?" + _ORD + r"(?!\w)|[ \t]*$))")
_PUNCT = re.compile(r"(?m)^[ \t]*(" + _N3 + r")[ \t]*[.)\-–][ \t]*(?=[^\s0-9۰-۹٠-٩.])")
_BARE = re.compile(r"(?m)^[ \t]*(" + _N3 + r")[ \t]+(?=[^\s0-9۰-۹٠-٩/.,:;()%\-–])")
_HLINE = re.compile(r"(?mi)^[ \t]*(" + _HEAD + r")(?!\w)([^\n]*)")
_SUB = re.compile(r"(?mi)^[ \t]*(?:تبصره|note|proviso|بند|clause|جزء|subclause|paragraph|item)(?!\w)")


def _positions(text: str) -> list[int]:
    """Unit starts. Bare numbers ("1 text", hyphen lost by extraction) only count
    inside a 1,2,3... sequence, so dates / amounts never split a unit."""
    c = [(m.start(), 0, None) for m in _STRUCT.finditer(text)]
    c += [(m.start(), 1, int(m[1].translate(_DIG))) for m in _PUNCT.finditer(text)]
    c += [(m.start(), 2, int(m[1].translate(_DIG))) for m in _BARE.finditer(text)]
    out, exp, last = [], 1, -1
    for pos, kind, n in sorted(c):
        if pos == last:
            continue
        if kind == 1:
            exp = n + 1
        elif kind == 2:
            if n == exp:
                exp += 1
            elif n == 1:
                exp = 2
            else:
                continue
        out.append(pos)
        last = pos
    return out


def split_units(text: str) -> list[str]:
    pos = _positions(text)
    if not pos:
        return [text] if text.strip() else []
    cuts = ([0] if pos[0] > 0 else []) + pos + [len(text)]
    return [text[a:b] for a, b in zip(cuts, cuts[1:]) if text[a:b].strip()]


def _heading(unit: str) -> Optional[str]:
    m = _HLINE.match(unit.lstrip())
    if m and (not m[2].strip() or re.match(r"(?i)[ \t]*(?:شماره[ \t]*)?" + _ORD + r"(?!\w)", m[2])):
        return m[0].strip()


def pack(units: list[str]) -> list[list[str]]:
    """Group a unit with its notes/clauses (and headings before it) into blocks,
    then fill chunks with whole blocks (never split a parent from its children)."""
    blocks, pend = [], []
    for u in units:
        if _heading(u):
            pend.append(u)
        elif _SUB.match(u.lstrip()) and blocks and not pend:
            blocks[-1].append(u)
        else:
            blocks.append(pend + [u])
            pend = []
    if pend:
        blocks.append(pend) if not blocks else blocks[-1].extend(pend)
    groups, cur, size = [], [], 0
    for b in blocks:
        s = sum(map(len, b))
        if cur and size + s > MAX_CHUNK:
            groups.append(cur)
            cur, size = [], 0
        cur += b
        size += s
    return groups + ([cur] if cur else [])


@dataclass
class Chunk:
    index: int
    text: str
    law: Optional[str]
    heading: Optional[str]      # last heading BEFORE this chunk


def extract_title(text: str) -> Optional[str]:
    m = re.search(r"(?mi)^[ \t]*(?:عنوان[^\n:：]{0,20}|title)[ \t]*[:：][ \t]*(.+)$", text[:5000])
    if m:
        return m[1].strip()
    m = re.search(r"(?m)^[ \t]*(?:قانون|آیین.?نامه|اساسنامه|مقرره|دستورالعمل|قرارداد|مصوبه|لایحه|طرح)[ \t]+[^\n]{3,180}$",
                  text[:5000])
    if m:
        return m[0].strip()
    for l in text[:1500].splitlines():
        l = l.strip()
        if 4 <= len(l) <= 180 and not re.search(r"[.!؟؛]$|[0-9۰-۹]{3}", l):
            return l


def build_chunks(text: str) -> list[Chunk]:
    law, head, out = extract_title(text), None, []
    for g in pack(split_units(text)):
        out.append(Chunk(len(out), "".join(g), law, head))
        for u in g:
            head = _heading(u) or head
    return out


def looks_legal(text: str) -> bool:
    return bool(re.search(r"(?mi)^[ \t]*(?:" + _LBL + r")(?!\w)", text) or len(_positions(text)) >= 2)


# ---------------------------------------------------------------- prompt
SYSTEM_PROMPT = """You extract legal units from a document of ANY jurisdiction, language or
type (statute, regulation, contract, judgment, policy...). Preserve hierarchy and source wording.
INCLUDE units with legal effect (rights, duties, prohibitions, permissions, definitions,
conditions, exceptions, sanctions, amounts, deadlines, amendments, operative transitional text).
EXCLUDE titles, tables of contents, cover letters, signatures, routing/registration metadata,
workflow/review forms, background narrative. If nothing legal is present, return an empty response.
RULES
- One record per separately labelled unit; never merge siblings; a parent's text stops before
  its labelled children (notes/provisos/clauses are separate records).
- Unlabelled continuation text stays with its nearest unit. Do not split on line wraps.
- Dates, percentages, amounts and cross-references are not structural labels.
- Do not summarize, translate or invent words; fix nothing you are unsure about.
- `text` must not repeat the unit's own label (put it in number_raw).
- parent_number = number of the immediate parent (e.g. the article of a note) or null.
SCHEMA (exactly): {"type": Article|Note|Clause|Subclause|Item|Paragraph|Definition|Provision|
Schedule|Appendix|Section|Chapter|Book, "number_raw": str|null, "number": int|null,
"parent_number": int|null, "book": str|null, "chapter": str|null, "text": str}
OUTPUT: ONLY JSONL, one JSON object per line, no markdown or comments."""


def _user_msg(c: Chunk) -> str:
    return (f"law: {c.law or 'unknown'}\ncurrent_heading_before_text: {c.heading or 'none'}\n\n"
            "TEXT:\n" + c.text)


# ---------------------------------------------------------------- model + parsing
def _model() -> str:
    return getattr(settings, "STRUCTURE_MODEL", None) or getattr(settings, "AVALAI_MODEL", None) or MODEL


def _clean(raw: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    return re.sub(r"\s*```$", "", re.sub(r"^```(?:jsonl?)?\s*", "", s, flags=re.I)).strip()


def parse_jsonl(raw: str) -> list[dict]:
    """Tolerant: JSONL, array, wrapper object, prose around objects."""
    s, dec, out, pos = _clean(raw), json.JSONDecoder(strict=False), [], 0

    def take(v):
        if isinstance(v, list):
            for x in v:
                take(x)
        elif isinstance(v, dict):
            for k in ("records", "items", "results", "data", "provisions"):
                if isinstance(v.get(k), list):
                    return take(v[k])
            if isinstance(v.get("text"), str) and v["text"].strip():
                out.append(v)
    while True:
        starts = [p for p in (s.find("{", pos), s.find("[", pos)) if p >= 0]
        if not starts:
            return out
        try:
            v, end = dec.raw_decode(s, min(starts))
        except json.JSONDecodeError:
            pos = min(starts) + 1
            continue
        take(v)
        pos = max(end, min(starts) + 1)


def _empty(raw: str) -> bool:
    s = _clean(raw)
    return s.lower() in {"", "[]", "{}", "null", "none"} or bool(re.fullmatch(r'\{\s*"\w+"\s*:\s*\[\s*\]\s*\}', s))


@dataclass
class Result:
    records: list = field(default_factory=list)
    error: Optional[str] = None
    empty: bool = False
    raw: str = ""


def call_model(client, c: Chunk) -> Result:
    err, raw, legal, empties = "unknown", "", looks_legal(c.text), 0
    for i in range(1, ATTEMPTS + 1):
        try:
            r = client.chat.completions.create(
                model=_model(), temperature=0, timeout=TIMEOUT,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": _user_msg(c)}])
            raw, fin = r.choices[0].message.content or "", getattr(r.choices[0], "finish_reason", None)
        except Exception as e:
            err = f"api_error: {e}"
            if i < ATTEMPTS:
                time.sleep(BACKOFF * i)
            continue
        if fin == "length":                      # cut-off answers lose records
            err = "truncated_output"
            continue
        recs = parse_jsonl(raw)
        if recs:
            return Result(records=recs, raw=raw)
        if _empty(raw):                          # "nothing legal here" is a valid answer
            if not legal:
                return Result(empty=True, raw=raw)
            empties += 1                         # legal-looking: ask once more, then trust the model
            if empties >= 2:
                return Result(empty=True, raw=raw)
            err = "empty_output_on_legal_looking_chunk"
        else:
            err = "invalid_output"
    return Result(error=err, raw=raw)


# ---------------------------------------------------------------- records
_ALIAS = {"article": "Article", "ماده": "Article", "note": "Note", "تبصره": "Note", "proviso": "Note",
          "exception": "Note", "clause": "Clause", "بند": "Clause", "subclause": "Subclause",
          "جزء": "Subclause", "item": "Item", "paragraph": "Paragraph", "section": "Section",
          "بخش": "Section", "chapter": "Chapter", "فصل": "Chapter", "book": "Book", "باب": "Book",
          "definition": "Definition", "provision": "Provision", "schedule": "Schedule",
          "appendix": "Appendix", "annex": "Appendix", "پیوست": "Appendix"}
_SKIP = {"title", "preamble", "intro", "signature", "raw", "review", "report", "coverletter",
         "tableofcontents", "toc", "metadata", "recital", "background"}
_RANK = {"Note": 1, "Clause": 1, "Subclause": 2, "Item": 2, "Paragraph": 2}
_FA = {"Article": "ماده", "Note": "تبصره", "Clause": "بند", "Subclause": "جزء", "Section": "بخش",
       "Chapter": "فصل", "Book": "باب"}
_LW = r"(?:" + _LBL + ")"


def _int(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    v = str(v).translate(_DIG).strip() if v is not None else ""
    return int(v) if v.isdigit() else None


def _s(v) -> Optional[str]:
    v = str(v).strip() if v is not None else ""
    return v or None


def _strip_label(text: str, nr: Optional[str]) -> str:
    """"1 ورود..." -> "ورود..." (label lives in number_raw); unchanged if no exact match."""
    if not nr:
        return text
    t = text.lstrip()
    tn, n = t.translate(_DIG), re.escape(nr.strip().translate(_DIG))
    for p in (n, _LW + r"[ \t]*" + n):
        m = re.match(r"(?i)" + p + r"(?!\w)[ \t]*[-–:.)]*[ \t]*\n?[ \t]*", tn)
        if m and m.end() < len(tn):
            return t[m.end():]
    return text


def _derive_number(nr: Optional[str]) -> Optional[int]:
    m = re.fullmatch(r"(?i)(?:" + _LW + r"[ \t]*)?(\S+)", (nr or "").translate(_DIG).strip())
    return None if not m else (int(m[1]) if m[1].isdigit() else _ORDV.get(m[1]))


def make_record(raw: dict, c: Chunk) -> Optional[dict]:
    text = _s(raw.get("text"))
    key = re.sub(r"[\s_\-]+", "", (_s(raw.get("type")) or "").casefold())
    if not text or key in _SKIP:
        return None
    typ = _ALIAS.get(key, "Provision")           # unknown labels kept, not dropped
    nr = _s(raw.get("number_raw"))
    text = _strip_label(text, nr)
    if typ in {"Book", "Chapter", "Section"} and "\n" not in text.strip() and len(text.strip()) <= 80:
        return None                              # heading-only
    return {"id": 0, "law_seq": 0, "law": _s(raw.get("law")) or c.law, "book": _s(raw.get("book")),
            "chapter": _s(raw.get("chapter")), "type": typ, "number_raw": nr,
            "number": _int(raw.get("number")) or _derive_number(nr),
            "parent_number": _int(raw.get("parent_number")), "parent_id": None,
            "text": text, "breadcrumb": ""}


def rule_records(c: Chunk, error: str) -> list[dict]:
    """Fallback when the model failed: one record per detected unit, text untouched."""
    out = []
    for u in split_units(c.text):
        m = re.match(r"(?i)[ \t]*(" + _LBL + r")?[ \t]*[-–:]?[ \t]*(" + _ORD + r"|[ا-ی](?!\w))?", u.lstrip())
        word, lab = (m[1] or "").casefold(), m[2] if m else None
        typ = _ALIAS.get(word, "Article" if lab and not word else "Provision")
        nr = " ".join(x for x in (m[1], lab) if x) or None
        out.append({"id": 0, "law_seq": 0, "law": c.law, "book": None, "chapter": c.heading,
                    "type": typ, "number_raw": nr, "number": _derive_number(nr),
                    "parent_number": None, "parent_id": None, "text": u.strip(),
                    "breadcrumb": "", "parse_error": error})
    return out


def _label(r: dict) -> str:
    nr = r.get("number_raw") or ""
    if re.match(_LW, nr, re.I):
        return nr
    fa = re.search(r"[\u0600-\u06FF]", r["text"])
    return f"{_FA.get(r['type'], r['type']) if fa else r['type']} {nr}".strip()


def finalize(recs: list[dict]) -> None:
    """ids, law_seq, parent_id (nearest preceding lower-rank unit; prefers parent_number),
    breadcrumb."""
    seq = {}
    for n, r in enumerate(recs, 1):
        seq[r["law"]] = seq.get(r["law"], 0) + 1
        r["id"], r["law_seq"] = n, seq[r["law"]]
    for i, r in enumerate(recs):
        rk = _RANK.get(r["type"])
        if not rk:
            continue
        lower = [p for p in recs[:i] if p["type"] not in _RANK or _RANK[p["type"]] < rk]
        pick = [p for p in lower if r["parent_number"] and p["number"] == r["parent_number"]] or lower
        if pick:
            r["parent_id"] = pick[-1]["id"]
            r["parent_number"] = r["parent_number"] or pick[-1]["number"]
    byid = {r["id"]: r for r in recs}
    for r in recs:
        p = byid.get(r["parent_id"])
        parts = [r["law"], r["book"], r["chapter"], _label(p) if p else None, _label(r)]
        r["breadcrumb"] = " > ".join(x for x in parts if x)


def _missing_articles(recs: list[dict]) -> list[int]:
    """Gaps in the 1..max sequence of top-level Article numbers (review hint only)."""
    nums = {r["number"] for r in recs if r["type"] == "Article" and r["number"]}
    return [n for n in range(1, max(nums) + 1) if n not in nums] if nums else []


@dataclass
class StructureResult:
    records: list
    data: dict
    total_chunks: int
    failed_chunks: int

    @property
    def jsonl(self) -> str:
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.records)

    def write_jsonl(self, path) -> None:
        """Write one JSON object per line (UTF-8, Persian kept readable)."""
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.jsonl, encoding="utf-8")

    @property
    def meta(self) -> dict:
        return self.data.get("meta", {})


def structure_text(text: str) -> StructureResult:
    """Always returns records. Model failures degrade to rule-based records
    (flagged with parse_error); only blank input raises."""
    text = normalize_text(text)
    chunks = build_chunks(text)
    if not chunks:
        raise ValueError("no text to structure")

    client, results = None, [None] * len(chunks)
    try:
        from openai import OpenAI
        key = getattr(settings, "AVALAI_API_KEY", None)
        if not key:
            raise RuntimeError("AVALAI_API_KEY is not configured")
        client = OpenAI(api_key=key, base_url=getattr(settings, "AVALAI_BASE_URL", None) or BASE_URL)
    except Exception as e:
        log.warning("LLM unavailable (%s): using rule-based fallback for all chunks", e)
        results = [Result(error=f"llm_unavailable: {e}") for _ in chunks]

    if client:
        def run(c):
            try:
                return call_model(client, c)
            except Exception as e:
                return Result(error=f"crash: {e}")
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(run, chunks))

    recs, failed, skipped = [], [], []
    for c, res in zip(chunks, results):
        got = [r for r in (make_record(x, c) for x in res.records) if r] if not res.error else []
        if got:
            recs += got
        elif not res.error:                      # model said "nothing legal" -> valid, not raw
            skipped.append({"chunk": c.index, "preview": c.text.strip()[:100]})
        else:
            failed.append({"chunk": c.index, "error": res.error, "raw_output": res.raw[:1000]})
            recs += rule_records(c, res.error)
    if not recs:                                 # guarantee output even if everything was filtered
        recs = rule_records(Chunk(0, text, chunks[0].law, None), "no_records_extracted")
    finalize(recs)

    meta = {"model": _model(), "generated_at": datetime.now(timezone.utc).isoformat(),
            "law": chunks[0].law, "total_chunks": len(chunks), "failed_chunks": len(failed),
            "skipped_chunks": len(skipped), "total_records": len(recs),
            "suspect_ids": [r["id"] for r in recs if r.get("parse_error")],
            "missing_article_numbers": _missing_articles(recs)}
    return StructureResult(recs, {"meta": meta, "records": recs, "failed": failed, "skipped": skipped},
                           len(chunks), len(failed))