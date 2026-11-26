#!/usr/bin/env python3
"""Build the Stage 4 submission pack in ``artifacts/stage4_submission/``.

One parser (Markdown → blocks), two serialisers (HTML for reading/printing,
ReportLab for the PDFs), one slide definition used by both. Nothing here touches
``app/`` or ``static/``.

Outputs
-------
* ``KathaPulse-AI-Stage4-Report.pdf|.html|.md`` — overview + validation report,
  cover, contents, and an appendix of the captured screenshots;
* ``KathaPulse-AI-Stage4-Pitch.pdf|.html`` — ten landscape slides;
* ``KathaPulse-AI-Stage4-Summary.pdf|.html|.md`` — the one-page paste-ready
  summary;
* copies of the evidence captures, the API proofs, the clean source ZIP,
  ``UPLOAD-CHECKLIST.md`` and ``SHA256SUMS.txt``.

Dependencies: the app's own environment plus **ReportLab** (build-only, not in
``requirements.txt``)::

    ./.venv/bin/pip install reportlab

Usage:
    ./.venv/bin/python scripts/build_stage4_pack.py
"""

from __future__ import annotations

import base64
import hashlib
import html
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "stage4_submission"
EVIDENCE = ROOT / "evidence"
#: Optional Indic fonts (not bundled in the repo): download once into .fonts/ —
#:   curl -fsSL -o .fonts/NotoSansMalayalam-Regular.ttf \
#:     https://raw.githubusercontent.com/notofonts/noto-fonts/main/hinted/ttf/NotoSansMalayalam/NotoSansMalayalam-Regular.ttf
#:   curl -fsSL -o .fonts/NotoSansDevanagari-Regular.ttf \
#:     https://raw.githubusercontent.com/notofonts/noto-fonts/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf
FONT_DIR = ROOT / ".fonts"
INDIC_FONTS = {
    "NotoML": FONT_DIR / "NotoSansMalayalam-Regular.ttf",
    "NotoDV": FONT_DIR / "NotoSansDevanagari-Regular.ttf",
}

BUILD = "v1.6.1"
DATE = "25 November 2026"

try:  # PDF rendering is optional so the HTML step works in a bare environment
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        HRFlowable,
        Image,
        KeepTogether,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    HAVE_PDF = True
except Exception:  # pragma: no cover - only when ReportLab is absent
    HAVE_PDF = False

INDIC_REGISTERED: list[str] = []
if HAVE_PDF:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for _name, _path in INDIC_FONTS.items():
        if _path.exists():
            try:
                pdfmetrics.registerFont(TTFont(_name, str(_path)))
                INDIC_REGISTERED.append(_name)
            except Exception:  # pragma: no cover
                pass


# ---------------------------------------------------------------------------
# Markdown -> blocks
# ---------------------------------------------------------------------------

INLINE_HTML = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
)


def inline_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    for pattern, repl in INLINE_HTML:
        escaped = pattern.sub(repl, escaped)
    return escaped


def inline_rl(text: str) -> str:
    """Markdown inline → ReportLab mini-HTML."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", out)
    if "NotoML" in INDIC_REGISTERED:
        out = re.sub(r"([\u0D00-\u0D7F](?:[\u0D00-\u0D7F\s]*[\u0D00-\u0D7F])?)",
                     r'<font name="NotoML">\1</font>', out)
    if "NotoDV" in INDIC_REGISTERED:
        out = re.sub(r"([\u0900-\u097F](?:[\u0900-\u097F\s]*[\u0900-\u097F])?)",
                     r'<font name="NotoDV">\1</font>', out)
    return out


def blocks(md: str) -> list[dict]:
    lines = md.splitlines()
    out: list[dict] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        if s.startswith("```"):
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append({"t": "code", "text": "\n".join(code)})
            continue

        if s.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].strip()) <= set("|-: "):
            head = [c.strip() for c in s.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append({"t": "table", "head": head, "rows": rows})
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if m:
            out.append({"t": "h" + str(len(m.group(1))), "text": m.group(2).strip()})
            i += 1
            continue

        if s in {"---", "***", "___"}:
            out.append({"t": "hr"})
            i += 1
            continue

        if s.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip("> ").strip())
                i += 1
            out.append({"t": "quote", "text": " ".join(quote)})
            continue

        marker = r"^\s*[-*]\s+" if re.match(r"^\s*[-*]\s+", raw) else None
        numbered = None if marker else r"^\s*\d+[.)]\s+"
        if marker or numbered:
            pattern = marker or numbered
            items = []
            while i < len(lines):
                if re.match(pattern, lines[i]):
                    items.append(re.sub(pattern, "", lines[i]).strip())
                    i += 1
                elif lines[i].strip() and lines[i].startswith(("  ", "\t")) and items:
                    items[-1] += " " + lines[i].strip()  # indented continuation
                    i += 1
                else:
                    break
            out.append({"t": "ul" if marker else "ol", "items": items})
            continue

        if not s:
            i += 1
            continue

        para = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^\s*(#{1,6}\s|[-*]\s|\d+[.)]\s|\||>|```|---$)", lines[i]
        ):
            para.append(lines[i].strip())
            i += 1
        out.append({"t": "p", "text": " ".join(para)})

    return out


# ---------------------------------------------------------------------------
# blocks -> HTML
# ---------------------------------------------------------------------------


def to_html(bs: list[dict]) -> str:
    out = []
    for b in bs:
        t = b["t"]
        if t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            lvl = t[1]
            out.append(f"<h{lvl}>{inline_html(b['text'])}</h{lvl}>")
        elif t == "p":
            out.append(f"<p>{inline_html(b['text'])}</p>")
        elif t == "quote":
            out.append(f"<blockquote><p>{inline_html(b['text'])}</p></blockquote>")
        elif t == "ul":
            out.append("<ul>" + "".join(f"<li>{inline_html(x)}</li>" for x in b["items"]) + "</ul>")
        elif t == "ol":
            out.append("<ol>" + "".join(f"<li>{inline_html(x)}</li>" for x in b["items"]) + "</ol>")
        elif t == "code":
            out.append("<pre><code>" + html.escape(b["text"]) + "</code></pre>")
        elif t == "hr":
            out.append("<hr />")
        elif t == "table":
            head = b["head"]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline_html(c)}</th>" for c in head) + "</tr></thead><tbody>")
            for row in b["rows"]:
                cells = (row + [""] * len(head))[: len(head)]
                out.append("<tr>" + "".join(f"<td>{inline_html(c)}</td>" for c in cells) + "</tr>")
            out.append("</tbody></table>")
    return "\n".join(out)


REPORT_CSS = """
@page { size: A4; margin: 17mm 15mm 16mm; }
body { font: 10.4pt/1.5 "Helvetica Neue", Arial, sans-serif; color: #14181f; margin: 0 auto; max-width: 800px; }
h1 { font-size: 21pt; line-height: 1.2; margin: 0 0 6pt; color: #0a2a1e; }
h2 { font-size: 14pt; margin: 22pt 0 8pt; padding-bottom: 4pt; border-bottom: 1.5px solid #0e7a4a; color: #0a3a26; }
h3 { font-size: 11.6pt; margin: 14pt 0 5pt; color: #123d2b; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0 12pt; font-size: 8.3pt; }
th, td { border: 0.6px solid #b9c3bd; padding: 3.4pt 4.5pt; vertical-align: top; text-align: left; }
th { background: #e8f2ec; font-weight: 700; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.6pt; background: #f2f4f3; padding: 0.5pt 2pt; }
pre { background: #f4f6f5; border-left: 3px solid #0e7a4a; padding: 7pt 9pt; white-space: pre-wrap; font-size: 8.4pt; }
pre code { background: none; padding: 0; }
blockquote { margin: 8pt 0; padding: 6pt 10pt; border-left: 3px solid #d99b1c; background: #fdf7e8; }
hr { border: none; border-top: 0.8px solid #cbd5cf; margin: 14pt 0; }
a { color: #0b5f3b; text-decoration: none; }
.cover { page-break-after: always; padding-top: 20mm; }
.cover h1 { font-size: 30pt; }
.cover .sub { font-size: 13pt; color: #234; margin: 4pt 0 20pt; }
.cover dl { display: grid; grid-template-columns: 36mm 1fr; gap: 3pt 8pt; font-size: 10pt; }
.cover dt { color: #52605a; } .cover dd { margin: 0; font-weight: 600; }
.cover .note { margin-top: 18mm; font-size: 9pt; color: #52605a; border-top: 0.8px solid #cbd5cf; padding-top: 8pt; }
.toc { margin-top: 8mm; font-size: 9.4pt; } .toc ol { margin: 4pt 0 0 12pt; padding: 0; }
figure { margin: 10pt 0 16pt; }
figure img { width: 100%; max-width: 88mm; border: 0.7px solid #c3cdc7; display: block; }
figcaption { font-size: 8.4pt; color: #4a5852; margin-top: 4pt; }
.watermark { font-size: 8.6pt; color: #7a4a00; background: #fff6e0; border: 0.7px dashed #d99b1c; padding: 5pt 7pt; }
.missing { color: #a11212; }
@media print { body { max-width: none; } h2 { page-break-after: avoid; } table, figure { page-break-inside: avoid; } }
"""

PITCH_CSS = """
@page { size: A4 landscape; margin: 0; }
body { margin: 0; font: 13pt/1.45 "Helvetica Neue", Arial, sans-serif; color: #eef4f1; }
.slide { width: 297mm; height: 210mm; padding: 16mm 18mm; page-break-after: always; background: #071019; position: relative; overflow: hidden; }
.slide h1 { font-size: 30pt; margin: 0 0 8pt; color: #5ef0a8; }
.slide h2 { font-size: 22pt; margin: 0 0 12pt; color: #5ef0a8; }
.slide p, .slide li { font-size: 12.5pt; color: #d6e2dc; }
.slide ul { margin: 6pt 0 0 16pt; padding: 0; } .slide li { margin-bottom: 5pt; }
.kicker { font-size: 10pt; letter-spacing: .16em; text-transform: uppercase; color: #86a597; }
.num { position: absolute; right: 14mm; bottom: 9mm; font-size: 9pt; color: #4f6a5e; }
.foot { position: absolute; left: 18mm; bottom: 9mm; font-size: 9pt; color: #4f6a5e; }
.two { display: flex; gap: 12mm; align-items: flex-start; } .two > div { flex: 1; }
.shot img { width: 100%; max-height: 148mm; object-fit: contain; object-position: top; border: 0.8px solid #24463a; background: #0b1620; }
.shot figcaption { font-size: 8.6pt; color: #86a597; margin-top: 4pt; }
table { width: 100%; border-collapse: collapse; font-size: 11pt; }
th, td { border-bottom: 0.6px solid #24463a; padding: 5pt 6pt; text-align: left; }
th { color: #5ef0a8; font-weight: 600; }
.big { font-size: 46pt; font-weight: 700; color: #5ef0a8; line-height: 1; }
.label { font-size: 10pt; color: #86a597; }
.stats { display: flex; gap: 10mm; margin-top: 8mm; } .stats > div { flex: 1; border-left: 3px solid #2b6b4f; padding-left: 7pt; }
.warn { background: #22180a; border: 0.8px dashed #d99b1c; color: #ffdf9e; padding: 7pt 9pt; font-size: 10pt; }
pre { font-size: 12pt; line-height: 1.6; background: #0b1620; border-left: 3px solid #2b6b4f; padding: 8pt 10pt; white-space: pre-wrap; color: #d6e2dc; }
"""


def data_uri(path: Path) -> str:
    return f"data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def figure_html(name: str, caption: str) -> str:
    path = EVIDENCE / name
    if not path.exists():
        return f'<p class="missing">[missing evidence file: {html.escape(name)}]</p>'
    return (
        f'<figure><img src="{data_uri(path)}" alt="{html.escape(caption)}" />'
        f"<figcaption>{inline_html(caption)}</figcaption></figure>"
    )


# ---------------------------------------------------------------------------
# Slides — one definition, two renderers
# ---------------------------------------------------------------------------

SLIDES: list[dict] = [
    {
        "kicker": "NeuraViz AI Challenge 2026–27 · Stage 4",
        "title": "KathaPulse AI",
        "lead": "Understand Your Medicine. Protect Your Health.",
        "body": [
            "A refusal-first, tri-lingual medicine-safety companion for Indian households and small "
            f"pharmacies. Working proof of concept, {BUILD}.",
        ],
        "stats": [("348", "backend checks"), ("119", "frontend checks"), ("256", "indexed medicines"), ("3", "languages, full parity")],
    },
    {
        "title": "The problem is not “what is this pill”",
        "bullets": [
            "Two brands, one molecule: Dolo 650 + Crocin = **1,300 mg paracetamol at once**; three doses of each reaches **5,850 mg/day** against a 4,000 mg ceiling.",
            "Look-alike neighbours: Telma vs Telma-H, Pan 40 vs Pan-D, Amaryl vs Amlopres — one letter, a different drug.",
            "Recalled and expired batches sit on the same shelf as good ones.",
            "The people most at risk read Malayalam or Hindi; the insert is English.",
            "Photographing medicine is sensitive; uploading it to an unknown cloud is not an acceptable default.",
        ],
    },
    {
        "title": "Who it is for",
        "bullets": [
            "Elderly patients and the family member managing their strips, in Kerala and across India.",
            "Small pharmacy counters checking a box before dispensing.",
            "Low-end Android phones, intermittent connectivity, 320 px screens, one hand.",
        ],
        "body": [
            "Design consequences: dark high-contrast UI, 44–58 px touch targets, no account, no app store, "
            "installable PWA, spoken warnings with an always-visible script.",
        ],
    },
    {
        "title": "One workflow, end to end",
        "pre": (
            "photograph strip\n"
            "  → canvas re-encode (EXIF/GPS dropped on the phone)\n"
            "  → read printed text (vision LLM → OCR → manual entry)\n"
            "  → resolve molecules against the local catalogue\n"
            "  → clinical rules (duplicate salt, ceiling, interactions, LASA, age)\n"
            "  → batch + expiry audit (pilot recall list, cold-chain flag)\n"
            "  → explain field by field, refuse or retake when unsure\n"
            "  → speak it in ml / hi / en, schedule the dose locally"
        ),
        "body": ["The model reads. The rules decide. The confidence gate decides when to refuse."],
    },
    {
        "title": "Refusal-first: the safety decision is not a model output",
        "bullets": [
            "Every warning comes from explicit rules over a fixed taxonomy — same input, same verdict, auditable.",
            "A **low**-confidence read is refused before any match; a **medium** read keeps its candidate but demands a retake. Both are field-level states, not a vague score.",
            "An unknown label never becomes a drug: the manual-entry path asks, then re-runs the same rules.",
            "Prompt injection is structurally useless: charset whitelist, instruction-phrase blocklist, no tool calls, no free-form generation.",
        ],
        "warn": "In this environment vision_keys: 0 — the AI-reading path is implemented and tested with stubbed provider responses, not demonstrated live. The confidence-gate captures in this pack are labelled “simulated confidence response”.",
    },
    {
        "kicker": "Evidence a judge can audit",
        "title": "What was actually read",
        "image": ("01-evidence-card-320.png", "(a) Identification evidence: name, strength, active ingredient, the database that verified it and its review date. 320 px, no overflow."),
        "bullets": [
            "Name, strength and ingredient are reported *separately*.",
            "A strength taken from the molecule default is shown **Unverified**, not as a camera read.",
            "Provenance names the catalogue and its review date (2026-11-25).",
            "Every result carries the screening-aid disclaimer and the RAM-only proof line.",
        ],
    },
    {
        "kicker": "The box, not just the molecule",
        "title": "Batch audit",
        "image": ("03-recall-banner-320.png", "(c) Glycomet 500 · batch GM2407A · expiry 09/2026: recall and expiry banner above the verdict, with the pharmacovigilance caveat."),
        "bullets": [
            "Parses 15 printed expiry shapes; unreadable dates are reported, never assumed safe.",
            "Matches the pilot recall list by molecule, brand token and batch prefix — no claim without a batch number.",
            "The caveat is explicit: a batch with no warning is **not** guaranteed safe, genuine or defect-free.",
            "Copy and speech exist in Malayalam and Hindi as well (captured in both).",
        ],
    },
    {
        "kicker": "Malayalam · Hindi · English",
        "title": "Heard, read, and never stored",
        "image": ("04-voice-reminder-ml.png", "(d) Malayalam: LISTEN, the voice-unavailable fallback notice headless Chromium really shows, the full script, and an active 1-0-1 reminder counting down."),
        "bullets": [
            "81 strings in all three languages, machine-checked for script (not transliteration).",
            "Speech uses ml-IN / hi-IN voices; with no voice installed the full warning stays on screen.",
            "Dose plans are computed on the server and held in the tab only — no localStorage, no schedule on disk.",
            "A schedule above the paracetamol ceiling is refused with the arithmetic shown.",
        ],
    },
    {
        "title": "Measured, not claimed",
        "table": (
            ["Check", "Result"],
            [
                ["Backend suite", "348 checks, 14 files, 0 failures"],
                ["Frontend suite", "119 checks, 9 Node suites, 0 failures"],
                ["Duplicate-salt corpus", "44 / 44"],
                ["Layout at 320 / 360 px", "scrollWidth == clientWidth at both (no overflow)"],
                ["Knowledge base", "256 / 256 indexed names structurally valid, 0 failures"],
                ["Translation inventory", "81 / 81 keys in en, ml, hi"],
                ["Image persistence", "0 disk writes: io.BytesIO only, no tempfile"],
            ],
        ),
        "body": [
            'Reproduce: pytest -o addopts="" -q · nine node *.test.mjs suites · python scripts/audit_knowledge_base.py.',
        ],
    },
    {
        "title": "What is not proven — and what comes next",
        "bullets": [
            "No live vision key here: the reading path is tested with stubs, not demonstrated on a real foil.",
            "Recall data is four curated pilot notices, not a CDSCO feed. MedicineWatch India is ahead on this.",
            "Malayalam and Hindi clinical wording has not been reviewed by a native clinical reviewer.",
            "Audible speech and the installed-PWA offline cycle need a physical phone; the visible fallback is what this pack shows.",
            "Not a medical device; not a substitute for a licensed pharmacist or doctor.",
        ],
        "body": [
            "**Next:** licensed formulary + live CDSCO ingest, clinical translation review, pharmacist pilot in Kochi, and a real-device accessibility pass.",
        ],
        "warn": "Ask us for the commit and run the suite yourself: every number above is reproducible.",
    },
]


def slide_html(index: int) -> str:
    s = SLIDES[index]
    if index == 0:
        stats = "".join(
            f'<div><p class="big">{v}</p><p class="label">{html.escape(l)}</p></div>' for v, l in s["stats"]
        )
        return (
            '<section class="slide"><p class="kicker">' + html.escape(s["kicker"]) + "</p>"
            f"<h1>{html.escape(s['title'])}</h1>"
            f'<p style="font-size:17pt;color:#b9d6c8">{html.escape(s["lead"])}</p>'
            f"<p>{inline_html(s['body'][0])}</p>"
            f'<div class="stats">{stats}</div><p class="num">1 / 10</p></section>'
        )
    parts = [f'<p class="kicker">{html.escape(s.get("kicker", "KathaPulse AI · Stage 4"))}</p>',
             f"<h2>{inline_html(s['title'])}</h2>"]
    left = ""
    right = []
    if "image" in s:
        left = '<div class="shot">' + figure_html(*s["image"]) + "</div>"
    for key in ("lead",):
        if key in s:
            right.append(f"<p>{inline_html(s[key])}</p>")
    if "pre" in s:
        right.append(f"<pre>{html.escape(s['pre'])}</pre>")
    if "table" in s:
        head, rows = s["table"]
        right.append(
            "<table><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{inline_html(c)}</td>" for c in r) + "</tr>" for r in rows)
            + "</table>"
        )
    if "bullets" in s:
        right.append("<ul>" + "".join(f"<li>{inline_html(b)}</li>" for b in s["bullets"]) + "</ul>")
    for para in s.get("body", []):
        right.append(f"<p>{inline_html(para)}</p>")
    if "warn" in s:
        right.append(f'<p class="warn">{inline_html(s["warn"])}</p>')
    if left:
        parts.append(f'<div class="two">{left}<div>{"".join(right)}</div></div>')
    else:
        parts.append("".join(right))
    parts.append(f'<p class="num">{index + 1} / 10</p>')
    parts.append('<p class="foot">Understand Your Medicine. Protect Your Health.</p>')
    return '<section class="slide">' + "".join(parts) + "</section>"


# ---------------------------------------------------------------------------
# ReportLab rendering
# ---------------------------------------------------------------------------


def _styles():
    sheet = getSampleStyleSheet()
    base = dict(fontName="Helvetica", textColor=colors.HexColor("#14181f"))
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24,
                             textColor=colors.HexColor("#0a2a1e"), spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13.5, leading=17,
                             textColor=colors.HexColor("#0a3a26"), spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11, leading=14,
                             textColor=colors.HexColor("#123d2b"), spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", fontSize=9.4, leading=13.2, spaceAfter=5, alignment=TA_LEFT, **base),
        "li": ParagraphStyle("li", fontSize=9.4, leading=13.0, leftIndent=10, bulletIndent=2, spaceAfter=2.5, **base),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=9.6,
                               backColor=colors.HexColor("#f4f6f5"), leftIndent=6, spaceAfter=6,
                               textColor=colors.HexColor("#1b2a24")),
        "quote": ParagraphStyle("quote", fontSize=9.4, leading=13, leftIndent=10, textColor=colors.HexColor("#4a3a12"),
                                backColor=colors.HexColor("#fdf7e8"), borderPadding=5, spaceAfter=6),
        "cell": ParagraphStyle("cell", fontSize=7.4, leading=9.2, **base),
        "cellh": ParagraphStyle("cellh", fontSize=7.4, leading=9.2, fontName="Helvetica-Bold",
                                textColor=colors.HexColor("#0a3a26")),
        "slide_h": ParagraphStyle("sh", fontName="Helvetica-Bold", fontSize=22, leading=26,
                                  textColor=colors.HexColor("#5ef0a8"), spaceAfter=10),
        "slide_title": ParagraphStyle("st", fontName="Helvetica-Bold", fontSize=32, leading=36,
                                      textColor=colors.HexColor("#5ef0a8"), spaceAfter=8),
        "slide_p": ParagraphStyle("sp", fontSize=11.5, leading=16, textColor=colors.HexColor("#d6e2dc"), spaceAfter=6),
        "slide_li": ParagraphStyle("sli", fontSize=11.5, leading=15.5, leftIndent=12, bulletIndent=2,
                                   textColor=colors.HexColor("#d6e2dc"), spaceAfter=3),
        "slide_kick": ParagraphStyle("sk", fontSize=8, leading=10, textColor=colors.HexColor("#86a597"), spaceAfter=4),
        "slide_warn": ParagraphStyle("sw", fontSize=9, leading=12.5, textColor=colors.HexColor("#ffdf9e"),
                                     backColor=colors.HexColor("#22180a"), borderPadding=6, spaceBefore=8),
        "slide_pre": ParagraphStyle("spr", fontName="Courier", fontSize=9, leading=12.5,
                                    textColor=colors.HexColor("#d6e2dc"), backColor=colors.HexColor("#0b1620"),
                                    borderPadding=6, leftIndent=2),
        "cell_dark": ParagraphStyle("cd", fontSize=10, leading=13, textColor=colors.HexColor("#d6e2dc")),
        "cell_dark_h": ParagraphStyle("cdh", fontSize=10, leading=13, fontName="Helvetica-Bold",
                                      textColor=colors.HexColor("#5ef0a8")),
        "sheet.title": sheet["Title"],
    }


def sliced_image(path: Path, max_h_mm: float, max_w_mm: float):
    """A tall phone capture as side-by-side slices that fit on one page.

    A 320 x 1,900 screenshot is 1:6; scaled to a readable width it is taller than
    A4. Cutting it into columns keeps the full card visible (nothing cropped away)
    while staying inside the frame.
    """
    from PIL import Image as PILImage

    im = PILImage.open(path)
    w, h = im.size
    ratio = h / w
    cols = max(1, math.ceil(ratio / 2.2))
    slice_h = h / cols
    slice_ratio = slice_h / w
    width_mm = min(max_w_mm / cols, max_h_mm / slice_ratio)
    height_mm = width_mm * slice_ratio
    tmpdir = Path(tempfile.mkdtemp(prefix="katha-slices-"))
    images = []
    for index in range(cols):
        top = int(index * slice_h)
        bottom = h if index == cols - 1 else int((index + 1) * slice_h)
        piece = tmpdir / f"{index}.png"
        im.crop((0, top, w, bottom)).save(piece)
        images.append(Image(str(piece), width=width_mm * mm, height=height_mm * mm))
    return images, width_mm, height_mm


def image_row(path: Path, max_h_mm: float, max_w_mm: float, gap_mm: float = 2.0):
    """Slices laid out in one borderless row; returns (flowable, mm height)."""
    images, width_mm, height_mm = sliced_image(path, max_h_mm, max_w_mm)
    cells: list = []
    widths: list = []
    for index, img in enumerate(images):
        if index:
            cells.append("")
            widths.append(gap_mm * mm)
        cells.append(img)
        widths.append(width_mm * mm)
    table = Table([cells], colWidths=widths)
    table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table, height_mm


def _wrap(text: str, width: int = 96) -> str:
    out = []
    for line in text.splitlines():
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > 20 else width
            out.append(line[:cut])
            line = line[cut:].lstrip()
        out.append(line)
    return "\n".join(out)


def blocks_to_flow(bs: list[dict], st, width: float) -> list:
    flow = []
    for b in bs:
        t = b["t"]
        if t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            lvl = t[1]
            style = st["h1"] if lvl == "1" else st["h2"] if lvl == "2" else st["h3"]
            flow.append(Paragraph(inline_rl(b["text"]), style))
            if lvl in {"1", "2"}:
                flow.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#0e7a4a"),
                                       spaceBefore=1, spaceAfter=6))
        elif t == "p":
            flow.append(Paragraph(inline_rl(b["text"]), st["p"]))
        elif t == "quote":
            flow.append(Paragraph(inline_rl(b["text"]), st["quote"]))
        elif t in {"ul", "ol"}:
            for n, item in enumerate(b["items"], 1):
                marker = "•" if t == "ul" else f"{n}."
                flow.append(Paragraph(inline_rl(item), st["li"], bulletText=marker))
        elif t == "code":
            flow.append(Paragraph(html.escape(_wrap(b["text"])).replace("\n", "<br/>"), st["code"]))
        elif t == "hr":
            flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5cf"),
                                   spaceBefore=6, spaceAfter=8))
        elif t == "table":
            head, rows = b["head"], b["rows"]
            data = [[Paragraph(inline_rl(c), st["cellh"]) for c in head]]
            for row in rows:
                cells = (row + [""] * len(head))[: len(head)]
                data.append([Paragraph(inline_rl(c), st["cell"]) for c in cells])
            weights = []
            for col in range(len(head)):
                longest = max([len(head[col])] + [len(r[col]) if col < len(r) else 0 for r in rows])
                weights.append(max(6, min(46, longest)))
            total = sum(weights)
            widths = [width * w / total for w in weights]
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c3bd")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f2ec")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            flow.append(table)
            flow.append(Spacer(1, 4))
    return flow


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    dark = doc.pagesize[0] > doc.pagesize[1]
    canvas.setFillColor(colors.HexColor("#4f6a5e" if dark else "#6b7a72"))
    canvas.drawString(15 * mm, 9 * mm, f"KathaPulse AI · Stage 4 · {BUILD} · {DATE}")
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 9 * mm, f"page {doc.page}")
    canvas.restoreState()


def doc_template(path: Path, pagesize=A4, margins=(15, 17, 15, 16), background: str | None = None) -> "BaseDocTemplate":
    left, top, right, bottom = (m * mm for m in margins)
    doc = BaseDocTemplate(
        str(path), pagesize=pagesize,
        leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
        title=path.stem, author="KathaPulse AI", subject="NeuraViz AI Challenge 2026–27 — Stage 4",
    )
    frame = Frame(left, bottom, pagesize[0] - left - right, pagesize[1] - top - bottom, id="body")

    def on_page(canvas, doc):
        if background:
            canvas.saveState()
            canvas.setFillColor(colors.HexColor(background))
            canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
            canvas.restoreState()
        _footer(canvas, doc)

    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])
    return doc


def render_report_pdf(path: Path, overview_md: str, validation_md: str) -> None:
    st = _styles()
    doc = doc_template(path)
    width = A4[0] - 30 * mm
    flow: list = []

    # cover
    flow.append(Spacer(1, 22 * mm))
    flow.append(Paragraph("KathaPulse AI — Stage 4 Final Report", ParagraphStyle(
        "cv", fontName="Helvetica-Bold", fontSize=28, leading=33, textColor=colors.HexColor("#0a2a1e"))))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph("Understand Your Medicine. Protect Your Health.", ParagraphStyle(
        "cs", fontSize=12.5, leading=16, textColor=colors.HexColor("#22403a"))))
    flow.append(Spacer(1, 12 * mm))
    meta = [
        ("Build", BUILD),
        ("Documents", "Submission overview + clinical/translation/offline validation"),
        ("Challenge", "NeuraViz AI Challenge 2026–27 — Stage 4 (Final Stage)"),
        ("Deadline", "10 December 2026 (confirm on the participant portal)"),
        ("Date", DATE),
        ("Backend checks", "348 passing"),
        ("Frontend checks", "119 passing"),
        ("Knowledge base", "48 brands · 256 indexed names · verified 2026-11-25"),
    ]
    for key, value in meta:
        flow.append(Paragraph(f"<b>{html.escape(key)}:</b> {html.escape(value)}", st["p"]))
    flow.append(Spacer(1, 10 * mm))
    flow.append(Paragraph(
        "Prepared for the NeuraViz AI Challenge 2026–27, Stage 4 (Final Stage). Every figure in this "
        "document is reproducible from the commit named in the pack manifest; where a check could not "
        "run in this environment, the document says so instead of estimating it.", st["quote"]))
    flow.append(PageBreak())

    headings = [re.sub(r"^\d+\.\s*", "", b["text"]) for b in blocks(overview_md + "\n" + validation_md) if b["t"] == "h2"]
    flow.append(Paragraph("Contents", st["h1"]))
    for n, h in enumerate(headings, 1):
        flow.append(Paragraph(f"{n}. {inline_rl(h)}", st["p"]))
    flow.append(PageBreak())

    flow += blocks_to_flow(blocks(overview_md), st, width)
    flow.append(PageBreak())
    flow += blocks_to_flow(blocks(validation_md), st, width)

    flow.append(PageBreak())
    flow.append(Paragraph("Appendix A — Visual evidence (Pass 36 captures)", st["h1"]))
    flow.append(Paragraph(
        "Captures (b) are labelled <b>simulated confidence response</b>: this environment has no vision "
        "key (vision_keys: 0), so the confidence gate was driven by an injected response while the UI "
        "path itself is the real client code. Captures (a), (c) and (d) are deterministic presets or "
        "live API responses.", st["quote"]))
    captions = [
        ("01-evidence-card-320.png", "(a) Successful scan, English, 320 px: verdict, identification evidence (name / strength / active ingredient), provenance “Kerala ground-truth catalogue · verified 2026-11-25”, screening disclaimer and the RAM-only proof line."),
        ("01-evidence-card-360.png", "(a) The same evidence card at 360 px: scrollWidth == clientWidth == 360, no horizontal overflow."),
        ("02-recapture-simulated.png", "(b) Medium confidence → amber “Retake a clearer photo” card, verdict held at “Could not verify”, all three evidence fields Unverified. Response labelled simulated."),
        ("02-low-rejected-simulated.png", "(b) Low confidence → the scan is rejected, the manual-entry card opens with batch/expiry/age fields, evidence stays Unverified. Response labelled simulated."),
        ("03-recall-banner-320.png", "(c) Glycomet 500, batch GM2407A, expiry 09/2026: crimson recall + expiry banner above the verdict, with the pharmacovigilance caveat (English)."),
        ("03-recall-banner-ml.png", "(c) The same banner and caveat in Malayalam."),
        ("03-recall-banner-hi.png", "(c) The same banner and caveat in Hindi."),
        ("04-voice-reminder-ml.png", "(d) Malayalam: LISTEN control, the voice-unavailable fallback notice headless Chromium really shows, the full read-aloud script, and an active 1-0-1 reminder banner counting down to 08:00."),
        ("04-voice-reminder-hi.png", "(d) Hindi: same controls and active reminder, re-rendered from the same in-memory plan."),
    ]
    for name, caption in captions:
        src = EVIDENCE / name
        if not src.exists():
            flow.append(Paragraph(f"[missing evidence file: {html.escape(name)}]", st["p"]))
            continue
        row, _ = image_row(src, max_h_mm=150, max_w_mm=min(width / mm - 4, 150))
        flow.append(KeepTogether([row, Spacer(1, 3), Paragraph(inline_rl(caption), st["cell"])]))
        flow.append(Spacer(1, 9))

    doc.build(flow)


def render_summary_pdf(path: Path, summary_md: str) -> None:
    st = _styles()
    doc = doc_template(path)
    width = A4[0] - 30 * mm
    body = summary_md.split("## Paste-ready summary (~100 words)", 1)
    flow: list = [
        Paragraph("KathaPulse AI — Stage 4 Summary", st["h1"]),
        Paragraph("A refusal-first, tri-lingual medicine-safety companion." + "<br/>" +
                  f"{BUILD} · NeuraViz AI Challenge 2026–27, Stage 4 · {DATE}", st["p"]),
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#0e7a4a"), spaceAfter=8),
    ]
    flow += blocks_to_flow(blocks(body[1] if len(body) > 1 else summary_md), st, width)
    doc.build(flow)


def render_pitch_pdf(path: Path) -> None:
    st = _styles()
    page = landscape(A4)
    doc = doc_template(path, pagesize=page, margins=(18, 16, 18, 14), background="#071019")
    width = page[0] - 36 * mm
    height = page[1] - 30 * mm
    flow: list = []
    for index, slide in enumerate(SLIDES):
        if index:
            flow.append(PageBreak())
            flow.append(Spacer(1, 12 * mm))
        flow.append(Paragraph(slide.get("kicker", "KathaPulse AI · Stage 4"), st["slide_kick"]))
        if index == 0:
            flow.append(Paragraph(slide["title"], st["slide_title"]))
            flow.append(Paragraph(slide["lead"], ParagraphStyle(
                "lead", fontSize=15, leading=19, textColor=colors.HexColor("#b9d6c8"), spaceAfter=10)))
            for para in slide.get("body", []):
                flow.append(Paragraph(inline_rl(para), st["slide_p"]))
            cols = [Paragraph(f"<b>{v}</b><br/><font size=8 color='#86a597'>{l}</font>",
                              ParagraphStyle("stat", fontSize=30, leading=32, textColor=colors.HexColor("#5ef0a8")))
                    for v, l in slide["stats"]]
            t = Table([cols], colWidths=[width / len(cols)] * len(cols))
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            flow.append(Spacer(1, 10 * mm))
            flow.append(t)
            continue

        flow.append(Paragraph(inline_rl(slide["title"]), st["slide_h"]))
        content: list = []
        if "pre" in slide:
            content.append(Paragraph(slide["pre"].replace("\n", "<br/>").replace(" ", "&nbsp;"), st["slide_pre"]))
        if "table" in slide:
            head, rows = slide["table"]
            data = [[Paragraph(html.escape(c), st["cell_dark_h"]) for c in head]]
            for r in rows:
                data.append([Paragraph(inline_rl(c), st["cell_dark"]) for c in r])
            t = Table(data, colWidths=[width * 0.36, width * 0.64], repeatRows=1)
            t.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#24463a")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            content.append(t)
        for bullet in slide.get("bullets", []):
            content.append(Paragraph(inline_rl(bullet), st["slide_li"], bulletText="•"))
        for para in slide.get("body", []):
            content.append(Paragraph(inline_rl(para), st["slide_p"]))
        if "warn" in slide:
            content.append(Paragraph(inline_rl(slide["warn"]), st["slide_warn"]))

        if "image" in slide:
            name, caption = slide["image"]
            src = EVIDENCE / name
            img_flow = []
            if src.exists():
                row, _ = image_row(src, max_h_mm=(height / mm) * 0.74, max_w_mm=(width / mm) * 0.40)
                img_flow.append(row)
                img_flow.append(Spacer(1, 3))
                img_flow.append(Paragraph(inline_rl(caption), ParagraphStyle(
                    "cap", fontSize=7.4, leading=9.4, textColor=colors.HexColor("#86a597"))))
            inner = Table([[img_flow, content]], colWidths=[width * 0.42, width * 0.56])
            inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            flow.append(inner)
        else:
            flow += content
    doc.build(flow)


# ---------------------------------------------------------------------------
# Assets and manifest
# ---------------------------------------------------------------------------


def cover_html(title: str, subtitle: str, rows: list[tuple[str, str]], toc: list[str]) -> str:
    items = "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd>" for k, v in rows)
    toc_html = ""
    if toc:
        toc_html = ('<div class="toc"><strong>Contents</strong><ol>'
                    + "".join(f"<li>{inline_html(t)}</li>" for t in toc) + "</ol></div>")
    return (
        f'<section class="cover"><h1>{html.escape(title)}</h1>'
        f'<p class="sub">{inline_html(subtitle)}</p><dl>{items}</dl>{toc_html}'
        '<p class="note">Prepared for the NeuraViz AI Challenge 2026–27, Stage 4 (Final Stage). '
        "Every figure in this document is reproducible from the commit named in the pack manifest; "
        "where a check could not run in this environment, the document says so.</p></section>"
    )


SUMMARY_MD = """# KathaPulse AI — final summary (Stage 4)

**Challenge:** NeuraViz AI Challenge 2026–27 — Stage 4 (Final Stage) ·
**Build:** `v1.6.1` · **Date:** 25 November 2026

## Paste-ready summary (~100 words)

KathaPulse AI helps Indian families and small pharmacies understand a medicine
before they take it. A patient photographs the strip in Malayalam, Hindi or
English; the app reads the printed name and strength, verifies the molecules
against a curated Kerala catalogue, and returns a deterministic safety verdict:
duplicate salt, paracetamol overdose, known interactions, look-alike brands, and
whether the batch is under a recall or past expiry. Every result shows what was
actually read, and refuses or asks for a clearer photo rather than guessing.
Images are processed in memory only and never stored. Dose reminders are spoken
in the patient's language and kept on their own phone.

**One-line pitch:** a refusal-first, tri-lingual medicine-safety companion that
explains what is in the box and protects the patient from the ways it can hurt
them.

## Results (measured)

| Check | Result |
|---|---|
| Backend suite | 348 checks, 14 files, 0 failures |
| Frontend suite | 119 checks, 9 Node suites, 0 failures |
| Duplicate-salt corpus | 44 / 44 |
| Layout, 320 px and 360 px | `scrollWidth == clientWidth`, no horizontal overflow |
| Knowledge base | 48 brands, 256 indexed names, 256 / 256 structurally valid, review date 2026-11-25 |
| Translation inventory | 81 / 81 strings in English, Malayalam and Hindi |
| Image handling | RAM only (`io.BytesIO`), zero disk writes, no `tempfile` |

## Why AI, honestly

The hard part is perception — reading a creased, glared, low-resolution foil —
not the safety decision. A vision model reads the text; deterministic rules over
a fixed catalogue decide the warning; a confidence gate decides when to refuse.
Unclear input produces a retake or manual entry, never a guess.

## What is deliberately not claimed

- No live vision model was demonstrated here (`vision_keys: 0`); scan results in
  the evidence pack are deterministic presets, and the confidence-gate captures
  are labelled **simulated confidence response**.
- The recall list is four curated **pilot** notices, not a CDSCO feed.
- Not a medical device, not CDSCO-certified, not a substitute for a licensed
  pharmacist or doctor.
- Malayalam and Hindi clinical wording has not had native clinical review.
"""


def build_report() -> list[Path]:
    overview = (ROOT / "docs" / "SUBMISSION_OVERVIEW.md").read_text(encoding="utf-8")
    validation = (ROOT / "docs" / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    overview = re.sub(r"\A# KathaPulse AI — Submission Overview.*?\n---\n", "", overview, flags=re.S)
    validation = re.sub(r"\A# KathaPulse AI —.*?\n---\n", "", validation, flags=re.S)

    headings = [b["text"] for b in blocks(overview + "\n" + validation) if b["t"] == "h2"]
    body = (
        cover_html(
            "KathaPulse AI — Stage 4 Final Report",
            "Understand Your Medicine. Protect Your Health.",
            [
                ("Build", BUILD),
                ("Documents", "Submission overview + clinical/translation/offline validation"),
                ("Challenge", "NeuraViz AI Challenge 2026–27 — Stage 4 (Final Stage)"),
                ("Deadline", "10 December 2026 (confirm on the participant portal)"),
                ("Date", DATE),
                ("Backend checks", "348 passing"),
                ("Frontend checks", "119 passing"),
                ("Knowledge base", "48 brands · 256 indexed names · verified 2026-11-25"),
            ],
            [re.sub(r"^\d+\.\s*", "", h) for h in headings[:24]],
        )
        + to_html(blocks(overview))
        + '<div style="page-break-before: always"></div>'
        + to_html(blocks(validation))
        + '<h2>Appendix A — Visual evidence (Pass 36 captures)</h2>'
        + '<p class="watermark">Captures (b) are labelled <strong>simulated confidence response</strong>: '
        "this environment has no vision key (<code>vision_keys: 0</code>), so the confidence gate was driven "
        "by an injected response while the UI path itself is the real client code.</p>"
        + "".join(figure_html(n, c) for n, c in [
            ("01-evidence-card-320.png", "(a) Successful scan, English, 320 px: verdict, identification evidence, provenance “Kerala ground-truth catalogue · verified 2026-11-25”, disclaimer and the RAM-only proof line."),
            ("01-evidence-card-360.png", "(a) The same evidence card at 360 px: scrollWidth == clientWidth == 360, no horizontal overflow."),
            ("02-recapture-simulated.png", "(b) Medium confidence → amber retake card, verdict held at “Could not verify”, evidence Unverified. Simulated response, labelled."),
            ("02-low-rejected-simulated.png", "(b) Low confidence → rejection wording plus the manual-entry card. Simulated response, labelled."),
            ("03-recall-banner-320.png", "(c) Glycomet 500 · GM2407A · 09/2026: recall + expiry banner above the verdict, pharmacovigilance caveat below (English)."),
            ("03-recall-banner-ml.png", "(c) The same banner and caveat in Malayalam."),
            ("03-recall-banner-hi.png", "(c) The same banner and caveat in Hindi."),
            ("04-voice-reminder-ml.png", "(d) Malayalam: LISTEN, the real no-voice fallback notice, full script, active 1-0-1 countdown."),
            ("04-voice-reminder-hi.png", "(d) Hindi: same controls and active reminder."),
        ])
    )
    html_path = OUT / "KathaPulse-AI-Stage4-Report.html"
    html_path.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>KathaPulse AI — Stage 4 Final Report</title>"
        f"<style>{REPORT_CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    md_path = OUT / "KathaPulse-AI-Stage4-Report.md"
    md_path.write_text(
        "# KathaPulse AI — Stage 4 Final Report\n\n"
        f"**Build:** {BUILD} · **Date:** {DATE} · **Challenge:** NeuraViz AI Challenge 2026–27, Stage 4\n\n"
        "---\n\n" + overview + "\n\n---\n\n" + validation, encoding="utf-8")
    paths = [html_path, md_path]
    if HAVE_PDF:
        pdf_path = OUT / "KathaPulse-AI-Stage4-Report.pdf"
        render_report_pdf(pdf_path, overview, validation)
        paths.append(pdf_path)
    return paths


def build_pitch() -> list[Path]:
    html_path = OUT / "KathaPulse-AI-Stage4-Pitch.html"
    html_path.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>KathaPulse AI — Stage 4 Pitch</title>"
        f"<style>{PITCH_CSS}</style></head><body>"
        + "".join(slide_html(i) for i in range(len(SLIDES)))
        + "</body></html>", encoding="utf-8")
    paths = [html_path]
    if HAVE_PDF:
        pdf_path = OUT / "KathaPulse-AI-Stage4-Pitch.pdf"
        render_pitch_pdf(pdf_path)
        paths.append(pdf_path)
    return paths


def build_summary() -> list[Path]:
    md_path = OUT / "KathaPulse-AI-Stage4-Summary.md"
    md_path.write_text(SUMMARY_MD, encoding="utf-8")
    body = (
        cover_html(
            "KathaPulse AI — Stage 4 Summary",
            "A refusal-first, tri-lingual medicine-safety companion.",
            [
                ("Build", BUILD),
                ("Challenge", "NeuraViz AI Challenge 2026–27, Stage 4 (Final Stage)"),
                ("Deadline", "10 December 2026"),
                ("Checks", "348 backend · 119 frontend · 256 / 256 knowledge-base entries"),
            ],
            [],
        )
        + to_html(blocks(SUMMARY_MD.split("## Paste-ready summary (~100 words)", 1)[1]))
    )
    html_path = OUT / "KathaPulse-AI-Stage4-Summary.html"
    html_path.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>KathaPulse AI — Stage 4 Summary</title>"
        f"<style>{REPORT_CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    paths = [html_path, md_path]
    if HAVE_PDF:
        pdf_path = OUT / "KathaPulse-AI-Stage4-Summary.pdf"
        render_summary_pdf(pdf_path, SUMMARY_MD)
        paths.append(pdf_path)
    return paths


def copy_assets() -> None:
    dest = OUT / "evidence"
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(EVIDENCE.glob("*")):
        if src.is_file() and not src.name.startswith("_") and src.suffix in {".png", ".jpg", ".json"}:
            shutil.copy2(src, dest / src.name)
    for src in sorted((ROOT / "artifacts").glob("kathapulse-ai-*.zip")):
        shutil.copy2(src, OUT / src.name)
    checklist = ROOT / "docs" / "STAGE4_UPLOAD_CHECKLIST.md"
    if checklist.exists():
        shutil.copy2(checklist, OUT / "UPLOAD-CHECKLIST.md")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest() -> Path:
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        commit = "unknown"
    lines = [f"# KathaPulse AI {BUILD} — Stage 4 pack · commit {commit} · built {DATE}", ""]
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{sha256(path)}  {path.relative_to(OUT)}")
    manifest = OUT / "SHA256SUMS.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*"):
        if stale.is_file():
            stale.unlink()
    written: list[Path] = []
    written += build_report()
    written += build_pitch()
    written += build_summary()
    copy_assets()
    manifest = write_manifest()
    print("Stage 4 pack written to", OUT)
    for path in written + [manifest]:
        print(f"  {path.name:<42} {path.stat().st_size:>9,} bytes")
    if not HAVE_PDF:
        print("ReportLab is not installed: PDFs were skipped (HTML/MD only).")
        print("  ./.venv/bin/pip install reportlab  &&  re-run this script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
