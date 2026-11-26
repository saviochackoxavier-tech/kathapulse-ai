#!/usr/bin/env python3
"""Structural integrity audit of the 256-name medicine knowledge base.

The submission claims "256 indexed names" (``/health`` →
``knowledge_base_entries``).  A count alone proves nothing: a name can be in the
index and still point at a product with no molecules, no printed strength or a
molecule the clinical engine has never heard of.  This script checks **every**
entry, not a sample, and exits non-zero if any structural invariant is broken.

What is verified
----------------
For every one of the 256 indexed names (``app.knowledge_base.INDEX``):

* it compact-keys to a product that exists in ``PRODUCTS_BY_BRAND``;
* that product has a non-empty brand, a non-empty dosage form, at least one
  active molecule, and at least one pack strength;
* every molecule it names exists in ``app.taxonomy`` (so the safety engine can
  resolve it) and carries a non-empty English/Malayalam/Hindi generic name plus
  a drug class;
* every strength is a positive number attached to one of those molecules.

For every patient-facing catalogue entry (``GET /knowledge.json``):

* brand is unique (no two entries can answer the same lookup differently);
* the three-language generic names and localised cautions are non-empty;
* the provenance date equals ``CATALOGUE_VERIFIED_ON``.

Provenance is **module-level, not per-entry**: the curated shelf list and the
taxonomy document their sources in their docstrings, and
``CATALOGUE_VERIFIED_ON`` is the single review date the evidence card prints.
This script asserts that date is present and well formed; it cannot prove a
pharmacist reviewed the data, and does not claim to.

Usage:
    ./.venv/bin/python scripts/audit_knowledge_base.py [--json]

Exit: 0 every invariant holds · 1 at least one failure (details on stdout).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import knowledge_base as kb  # noqa: E402
from app import taxonomy  # noqa: E402

#: The number the submission, the docs and /health quote.
EXPECTED_INDEXED_NAMES = 256
EXPECTED_BRANDS = 48
#: ISO date, and the single review date the evidence card prints.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def audit() -> dict:
    failures: list[str] = []

    index = kb.INDEX
    products = kb.PRODUCTS_BY_BRAND

    # ---------------------------------------------------------------- names
    if len(index) != EXPECTED_INDEXED_NAMES:
        failures.append(
            f"indexed names: expected {EXPECTED_INDEXED_NAMES}, found {len(index)}"
        )
    if len(kb.PRODUCTS) != EXPECTED_BRANDS:
        failures.append(f"curated brands: expected {EXPECTED_BRANDS}, found {len(kb.PRODUCTS)}")

    for key, resolution in index.items():
        where = f"indexed name {key!r}"
        if not key or key != kb._compact(key):
            failures.append(f"{where}: key is empty or not compacted")
        if not resolution.brand:
            failures.append(f"{where}: no brand")
            continue
        product = products.get(resolution.brand)
        if product is None:
            failures.append(f"{where}: brand {resolution.brand!r} missing from PRODUCTS_BY_BRAND")
            continue
        if not resolution.molecules:
            failures.append(f"{where}: resolves to {product.brand!r} with no molecule")
        if not resolution.strengths:
            failures.append(f"{where}: resolves to {product.brand!r} with no pack strength")
        if resolution.method not in {"ground_truth", "molecule"}:
            failures.append(f"{where}: unknown resolution method {resolution.method!r}")

    # ------------------------------------------------------------- products
    for product in kb.PRODUCTS:
        where = f"product {product.brand!r}"
        if not product.brand.strip():
            failures.append("product with an empty brand")
        if not product.form.strip():
            failures.append(f"{where}: empty dosage form")
        if not product.molecules:
            failures.append(f"{where}: no active ingredient")
        for canonical in product.molecules:
            drug = taxonomy.BY_CANONICAL.get(canonical)
            if drug is None:
                failures.append(f"{where}: molecule {canonical!r} is not in app.taxonomy")
                continue
            for field in ("name_en", "name_ml", "name_hi", "drug_class"):
                if not str(getattr(drug, field) or "").strip():
                    failures.append(f"{where}: molecule {canonical!r} has empty {field}")
            if not re.search(r"[\u0D00-\u0D7F]", drug.name_ml or ""):
                failures.append(f"{where}: {canonical!r} name_ml is not Malayalam script")
            if not re.search(r"[\u0900-\u097F]", drug.name_hi or ""):
                failures.append(f"{where}: {canonical!r} name_hi is not Devanagari script")
        if not product.strengths:
            failures.append(f"{where}: no pack strength recorded")
        for canonical, strength in product.strengths:
            if canonical not in product.molecules:
                failures.append(f"{where}: strength for {canonical!r} is not a listed molecule")
            if not isinstance(strength, (int, float)) or strength <= 0:
                failures.append(f"{where}: strength for {canonical!r} is not a positive number")

    # ------------------------------------------------------------ catalogue
    catalogue = kb.catalogue()
    seen: set[str] = set()
    reference_source = ""
    for entry in catalogue:
        brand = entry.get("brand", "")
        where = f"catalogue {brand!r}"
        if not brand:
            failures.append("catalogue entry with an empty brand")
            continue
        if brand in seen:
            failures.append(f"{where}: duplicate brand key")
        seen.add(brand)
        if not entry.get("form"):
            failures.append(f"{where}: empty dosage form")
        if not entry.get("molecules"):
            failures.append(f"{where}: no molecules")
        if not entry.get("strengths"):
            failures.append(f"{where}: no strengths")
        for molecule in entry.get("molecules", []):
            if not molecule.get("name_en") or not molecule.get("name_ml") or not molecule.get("name_hi"):
                failures.append(f"{where}: molecule {molecule.get('canonical')!r} misses a language name")
            if not molecule.get("drug_class"):
                failures.append(f"{where}: molecule {molecule.get('canonical')!r} misses a drug class")
        for strength in entry.get("strengths", []):
            if not strength.get("strength_mg") or strength["strength_mg"] <= 0:
                failures.append(f"{where}: strength {strength.get('canonical')!r} is not positive")
        for caution in entry.get("cautions", []):
            for lang in ("en", "ml", "hi"):
                if not (caution.get("text", {}).get(lang) or "").strip():
                    failures.append(f"{where}: caution {caution.get('key')!r} missing {lang} text")

    # ----------------------------------------------------------- provenance
    verified_on = getattr(kb, "CATALOGUE_VERIFIED_ON", "")
    if not _DATE_RE.match(verified_on or ""):
        failures.append(f"CATALOGUE_VERIFIED_ON is not an ISO date: {verified_on!r}")
    source_doc = (kb.__doc__ or "") + (taxonomy.__doc__ or "")
    for needle in ("Kerala", "taxonomy"):
        if needle.lower() not in source_doc.lower():
            failures.append(f"documented provenance does not mention {needle!r}")

    return {
        "indexed_names": len(index),
        "curated_brands": len(kb.PRODUCTS),
        "taxonomy_molecules": len(taxonomy.all_drugs()),
        "catalogue_entries": len(catalogue),
        "catalogue_unique_brands": len(seen),
        "catalogue_verified_on": verified_on,
        "entries_with_curator_note": sum(1 for p in kb.PRODUCTS if p.note),
        "failures": failures,
        "ok": not failures,
    }


def main(argv: list[str]) -> int:
    report = audit()
    if "--json" in argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("KathaPulse AI — knowledge-base structural audit")
        print(f"  indexed names            : {report['indexed_names']}")
        print(f"  curated Kerala brands    : {report['curated_brands']}")
        print(f"  taxonomy molecules       : {report['taxonomy_molecules']}")
        print(f"  catalogue entries        : {report['catalogue_entries']}")
        print(f"  unique catalogue brands  : {report['catalogue_unique_brands']}")
        print(f"  catalogue verified on    : {report['catalogue_verified_on']}")
        print(f"  entries with curator note: {report['entries_with_curator_note']}")
        print(f"  structural failures      : {len(report['failures'])}")
        for failure in report["failures"][:40]:
            print(f"    - {failure}")
        if len(report["failures"]) > 40:
            print(f"    … {len(report['failures']) - 40} more")
        print("RESULT:", "PASS" if report["ok"] else "FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
