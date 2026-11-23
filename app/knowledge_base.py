"""Kerala & national essential-medicine ground truth.

Why this module exists
----------------------
The taxonomy knows *which molecule a brand contains*.  It does not know how a
pharmacist in Kochi talks about the box, and it does not know the cautions that
make a molecule worth a second look in an elderly patient.  This module adds
that layer, and then uses it as a **deterministic fallback** for text the vision
or OCR tier returned imperfectly:

    "Glycomet GP"      -> Glycomet-GP (metformin + glimepiride), not metformin
    "Amaryll 2"        -> Amaryl (glimepiride)
    "PAN D"            -> Pan-D (pantoprazole + domperidone)
    "Augmentn 625"     -> Augmentin (amoxicillin + clavulanic acid)

Matching is **space- and dash-insensitive** ("glycometgp" == "Glycomet-GP") and
then falls back to a character-similarity score with a hard floor.  It never
invents a drug: a miss returns ``None`` and the caller keeps asking the user,
which is the only honest behaviour when the photo is unreadable.

Data honesty
------------
* Every molecule named here exists in ``app.taxonomy``; a unit test enforces it,
  so this file can never introduce a drug the clinical engine does not know.
* Cautions are plain-language advisories for the *catalogue* (pharmacist
  reference and ``/knowledge.json``), not diagnoses.  The only thing that
  becomes a patient-facing finding is an age-band warning, and only when the
  request actually supplies an age.
* This is a curated pilot dataset (Kerala shelf products, Indian pack
  strengths), not a licensed formulary.  A deployment swaps ``PRODUCTS`` for a
  licensed feed; the matcher does not change.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from . import taxonomy

#: Below this similarity a candidate is a guess, and a guess is never returned.
FUZZY_MIN_SCORE = 0.88

#: Containment matching on very short keys ("o2", "pan") produces false hits.
MIN_KEY_LEN = 4

#: Shortest *input* worth fuzzy-matching at all.
MIN_INPUT_LEN = 5


@dataclass(frozen=True)
class Product:
    """One printed product: brand, molecules, pack strengths and cautions."""

    brand: str
    molecules: tuple[str, ...]
    strengths: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    form: str = "tablet"
    #: Plain-language caution keys, rendered by ``i18n`` as ``kb.caution.<key>``.
    cautions: tuple[str, ...] = field(default_factory=tuple)
    #: Outside this band the age rule fires (only when the request has an age).
    age_min: int | None = None
    age_max: int | None = None
    #: Short English note for pharmacist tooling; never spoken.
    note: str = ""


# ---------------------------------------------------------------------------
# Curated Kerala shelf products (Indian pack strengths)
# ---------------------------------------------------------------------------

PRODUCTS: tuple[Product, ...] = (
    # -- blood pressure ----------------------------------------------------
    Product("Telma 40", ("telmisartan",), (("telmisartan", 40),), cautions=("pregnancy", "kidney")),
    Product(
        "Telma-H",
        ("telmisartan", "hydrochlorothiazide"),
        (("telmisartan", 40), ("hydrochlorothiazide", 12.5)),
        cautions=("pregnancy", "kidney"),
        note="The H is hydrochlorothiazide: a second molecule, not a stronger Telma.",
    ),
    Product(
        "Telma-AM",
        ("telmisartan", "amlodipine"),
        (("telmisartan", 40), ("amlodipine", 5)),
        cautions=("pregnancy", "kidney"),
    ),
    Product("Losar 50", ("losartan",), (("losartan", 50),), cautions=("pregnancy", "kidney")),
    Product("Cardace 5", ("ramipril",), (("ramipril", 5),), cautions=("pregnancy", "kidney")),
    Product("Amlopres 5", ("amlodipine",), (("amlodipine", 5),), cautions=("heart_failure",)),
    Product("Met XL 50", ("metoprolol",), (("metoprolol", 50),), cautions=("asthma", "heart_failure")),
    Product("Metolar 50", ("metoprolol",), (("metoprolol", 50),), cautions=("asthma",)),
    # -- pain and fever ----------------------------------------------------
    Product("Dolo 650", ("paracetamol",), (("paracetamol", 650),), cautions=("liver",)),
    Product(
        "Crocin Advance",
        ("paracetamol",),
        (("paracetamol", 500),),
        cautions=("liver",),
        note="Same molecule as Dolo: two brands, one paracetamol ceiling.",
    ),
    Product(
        "Calpol 250",
        ("paracetamol",),
        (("paracetamol", 250),),
        form="syrup",
        cautions=("liver",),
        note="Paediatric syrup: dose by weight, never by age alone.",
    ),
    Product(
        "Combiflam",
        ("ibuprofen", "paracetamol"),
        (("ibuprofen", 400), ("paracetamol", 325)),
        cautions=("ulcer", "kidney", "heart_failure"),
        age_max=65,
    ),
    Product(
        "Zerodol-SP",
        ("aceclofenac", "paracetamol"),
        (("aceclofenac", 100), ("paracetamol", 325)),
        cautions=("ulcer", "kidney", "heart_failure"),
        age_max=65,
    ),
    Product(
        "Hifenac-P",
        ("aceclofenac", "paracetamol"),
        (("aceclofenac", 100), ("paracetamol", 325)),
        cautions=("ulcer", "kidney"),
        age_max=65,
    ),
    Product("Voveran 50", ("diclofenac",), (("diclofenac", 50),), cautions=("ulcer", "kidney", "heart_failure"), age_max=65),
    Product(
        "Ultracet",
        ("tramadol", "paracetamol"),
        (("tramadol", 37.5), ("paracetamol", 325)),
        cautions=("drowsy", "liver"),
        age_max=75,
    ),
    # -- diabetes ----------------------------------------------------------
    Product("Glycomet 500", ("metformin",), (("metformin", 500),), cautions=("kidney", "liver")),
    Product(
        "Glycomet-GP",
        ("metformin", "glimepiride"),
        (("metformin", 500), ("glimepiride", 1)),
        cautions=("kidney", "low_sugar"),
        age_max=65,
        note="GP = glimepiride added: a tablet that can drop sugar, unlike plain Glycomet.",
    ),
    Product("Amaryl 1", ("glimepiride",), (("glimepiride", 1),), cautions=("low_sugar",), age_max=65),
    Product("Januvia 100", ("sitagliptin",), (("sitagliptin", 100),), cautions=("kidney",)),
    Product("Galvus 50", ("vildagliptin",), (("vildagliptin", 50),), cautions=("liver",)),
    # -- stomach and gut ---------------------------------------------------
    Product("Pan 40", ("pantoprazole",), (("pantoprazole", 40),), note="Take 30-60 minutes before food."),
    Product(
        "Pan-D",
        ("pantoprazole", "domperidone"),
        (("pantoprazole", 40), ("domperidone", 30)),
        cautions=("heart_failure",),
        note="Pan-D is not a stronger Pan 40: it adds domperidone, which affects heart rhythm.",
    ),
    Product("Omez 20", ("omeprazole",), (("omeprazole", 20),)),
    Product("Domstal 10", ("domperidone",), (("domperidone", 10),), cautions=("heart_failure",)),
    Product("Emeset 4", ("ondansetron",), (("ondansetron", 4),), cautions=("heart_failure",)),
    # -- antibiotics -------------------------------------------------------
    Product(
        "Augmentin 625",
        ("amoxicillin", "clavulanic_acid"),
        (("amoxicillin", 500), ("clavulanic_acid", 125)),
        cautions=("liver",),
        note="Complete the course; a half course breeds resistance.",
    ),
    Product(
        "Clavam 625",
        ("amoxicillin", "clavulanic_acid"),
        (("amoxicillin", 500), ("clavulanic_acid", 125)),
        cautions=("liver",),
    ),
    Product("Azee 500", ("azithromycin",), (("azithromycin", 500),), cautions=("liver",)),
    Product("Cifran 500", ("ciprofloxacin",), (("ciprofloxacin", 500),), cautions=("sun",), age_min=18),
    Product("O2 200", ("ofloxacin",), (("ofloxacin", 200),), cautions=("sun",), age_min=18),
    Product("Flagyl 400", ("metronidazole",), (("metronidazole", 400),), cautions=("pregnancy", "liver")),
    Product("Doxy 100", ("doxycycline",), (("doxycycline", 100),), cautions=("sun",), age_min=8),
    # -- heart, cholesterol, blood -----------------------------------------
    Product("Ecosprin 75", ("aspirin",), (("aspirin", 75),), cautions=("bleeding", "ulcer"), age_min=16),
    Product("Loprin 75", ("aspirin",), (("aspirin", 75),), cautions=("bleeding", "ulcer"), age_min=16),
    Product("Clopilet 75", ("clopidogrel",), (("clopidogrel", 75),), cautions=("bleeding",)),
    Product("Warf 5", ("warfarin",), (("warfarin", 5),), cautions=("bleeding", "ulcer")),
    Product("Atorva 10", ("atorvastatin",), (("atorvastatin", 10),), cautions=("liver", "pregnancy")),
    Product("Rosuvas 10", ("rosuvastatin",), (("rosuvastatin", 10),), cautions=("liver", "pregnancy")),
    Product("Lasix 40", ("furosemide",), (("furosemide", 40),), cautions=("kidney", "low_sugar")),
    # -- thyroid, steroid, allergy, mood -----------------------------------
    Product("Thyronorm 50", ("levothyroxine",), (("levothyroxine", 50),), cautions=("heart_failure",),
            note="Take on an empty stomach, 30 minutes before food."),
    Product("Wysolone 10", ("prednisolone",), (("prednisolone", 10),), cautions=("ulcer", "heart_failure")),
    Product(
        "Montair-LC",
        ("montelukast", "levocetirizine"),
        (("montelukast", 10), ("levocetirizine", 5)),
        cautions=("drowsy",),
    ),
    Product("Cetzine 10", ("cetirizine",), (("cetirizine", 10),), cautions=("drowsy",)),
    Product("Daxid 50", ("sertraline",), (("sertraline", 50),), cautions=("drowsy",)),
    Product("Alprax 0.5", ("alprazolam",), (("alprazolam", 0.5),), cautions=("drowsy",), age_min=18, age_max=65),
    Product("Manforce 50", ("sildenafil",), (("sildenafil", 50),), cautions=("heart_failure",)),
    Product("Asthalin", ("salbutamol",), (("salbutamol", 2),), form="inhaler", cautions=("heart_failure",)),
)

#: Class-level defaults, so a molecule without a curated product still answers
#: with the right caution (and the right age band) instead of nothing.
CLASS_DEFAULTS: dict[str, tuple[tuple[str, ...], int | None, int | None]] = {
    "nsaid": (("ulcer", "kidney", "heart_failure"), None, 65),
    "paracetamol": (("liver",), None, None),
    "opioid": (("drowsy",), 12, 75),
    "sulfonylurea": (("low_sugar",), None, 65),
    "biguanide": (("kidney", "liver"), None, None),
    "dpp4": (("kidney",), None, None),
    "arb": (("pregnancy", "kidney"), None, None),
    "acei": (("pregnancy", "kidney"), None, None),
    "beta_blocker": (("asthma", "heart_failure"), None, None),
    "statin": (("liver", "pregnancy"), None, None),
    "antiplatelet": (("bleeding", "ulcer"), 16, None),
    "anticoagulant": (("bleeding",), None, None),
    "benzodiazepine": (("drowsy",), 18, 65),
    "ssri": (("drowsy",), 18, None),
    "antihistamine": (("drowsy",), None, None),
    "tetracycline": (("sun",), 8, None),
    "fluoroquinolone": (("sun",), 18, None),
    "macrolide": (("liver",), None, None),
    "penicillin": (("liver",), None, None),
    "nitroimidazole": (("pregnancy", "liver"), None, None),
    "corticosteroid": (("ulcer", "heart_failure"), None, None),
    "thyroid_hormone": (("heart_failure",), None, None),
    "diuretic_loop": (("kidney", "low_sugar"), None, None),
    "diuretic_k_sparing": (("kidney",), None, None),
    "prokinetic": (("heart_failure",), None, None),
    "antiemetic": (("heart_failure",), None, None),
    "pde5": (("heart_failure",), 18, None),
    "bronchodilator": (("heart_failure",), None, None),
    "ccb": (("heart_failure",), None, None),
    "thiazide": (("kidney",), None, None),
    "nitrate": ((), None, None),
    "leukotriene": ((), None, None),
    "ppi": ((), None, None),
    "beta_lactamase_inhibitor": (("liver",), None, None),
}

#: Per-molecule overrides where the class default would be wrong.
_MOLECULE_OVERRIDES: dict[str, tuple[tuple[str, ...], int | None, int | None]] = {
    "aspirin": (("bleeding", "ulcer"), 16, None),
    "metronidazole": (("pregnancy", "liver"), None, None),
    "levothyroxine": (("heart_failure",), None, None),
    "domperidone": (("heart_failure",), None, None),
    "ondansetron": (("heart_failure",), None, None),
    "furosemide": (("kidney", "low_sugar"), None, None),
    "prednisolone": (("ulcer", "heart_failure"), None, None),
    "salbutamol": (("heart_failure",), None, None),
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """A verified answer from the local ground truth."""

    brand: str
    molecules: tuple[str, ...]
    strengths: tuple[tuple[str, float], ...]
    score: float
    method: str  # "ground_truth" (exact index) | "fuzzy" | "molecule"


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", taxonomy.normalise(str(text or "")))


def _molecule_product(drug: taxonomy.Drug) -> Product:
    cautions, age_min, age_max = _MOLECULE_OVERRIDES.get(
        drug.canonical, CLASS_DEFAULTS.get(drug.drug_class, ((), None, None))
    )
    strengths = (
        ((drug.canonical, drug.default_strength),) if drug.default_strength else ()
    )
    return Product(
        brand=drug.name_en,
        molecules=(drug.canonical,),
        strengths=strengths,
        cautions=cautions,
        age_min=age_min,
        age_max=age_max,
    )


def _build_index() -> tuple[dict[str, Resolution], dict[str, Product]]:
    """Compact key -> resolution, brand first, then combos, then molecules."""
    index: dict[str, Resolution] = {}
    products: dict[str, Product] = {}

    def add(text: str, product: Product, method: str) -> None:
        key = _compact(text)
        if len(key) < MIN_KEY_LEN or key in index:
            return  # never let a later, weaker entry overwrite a brand
        index[key] = Resolution(
            brand=product.brand,
            molecules=tuple(
                m for m in product.molecules if m in taxonomy.BY_CANONICAL
            ),
            strengths=product.strengths,
            score=1.0,
            method=method,
        )

    # 1. Curated Kerala brands, longest name first so "Telma-AM" beats "Telma".
    for product in sorted(PRODUCTS, key=lambda p: len(p.brand), reverse=True):
        products[product.brand] = product
        add(product.brand, product, "ground_truth")

    # 2. Fixed combinations and molecule aliases straight from the taxonomy.
    for drug in taxonomy.all_drugs():
        product = _molecule_product(drug)
        products.setdefault(product.brand, product)
        for alias in (drug.canonical, drug.name_en, *drug.aliases):
            add(alias, product, "molecule")

    return index, products


INDEX, PRODUCTS_BY_BRAND = _build_index()


def stats() -> dict[str, int]:
    """Real counts, for /health and the docs — never a rounded-up marketing number."""
    return {
        "brands": len(PRODUCTS),
        "molecules": len(taxonomy.all_drugs()),
        "indexed_names": len(INDEX),
    }


def resolve(text: str, *, fuzzy: bool = True) -> Resolution | None:
    """Resolve printed text against the local ground truth.

    1. **Containment** on the compact form, longest key first: ``"glycometgp"``
       hits ``Glycomet-GP`` rather than ``Glycomet``, and spacing/dashes do not
       matter.
    2. **Similarity** (``difflib``, floor :data:`FUZZY_MIN_SCORE`) for OCR slips
       such as ``"amaryll"`` or ``"augmentn625"``.

    Returns ``None`` when nothing is close enough — the caller must keep asking
    the user rather than showing a drug that was never printed.
    """
    compact = _compact(text)
    if len(compact) < MIN_KEY_LEN:
        return None

    best: Resolution | None = None
    for key, resolution in INDEX.items():
        if key in compact:
            if best is None or len(key) > len(best.brand):
                best = resolution
    if best is not None:
        return best

    if not fuzzy or len(compact) < MIN_INPUT_LEN:
        return None
    match = difflib.get_close_matches(compact, list(INDEX), n=1, cutoff=FUZZY_MIN_SCORE)
    if not match:
        return None
    hit = INDEX[match[0]]
    score = difflib.SequenceMatcher(None, compact, match[0]).ratio()
    return Resolution(
        brand=hit.brand,
        molecules=hit.molecules,
        strengths=hit.strengths,
        score=round(score, 3),
        method="fuzzy",
    )


# ---------------------------------------------------------------------------
# Cautions and age bands
# ---------------------------------------------------------------------------


def product_for(brand: str) -> Product | None:
    return PRODUCTS_BY_BRAND.get(brand)


def molecules_in(brand: str) -> tuple[str, ...]:
    product = PRODUCTS_BY_BRAND.get(brand)
    return product.molecules if product else ()


def cautions_for(canonical: str) -> tuple[str, ...]:
    drug = taxonomy.BY_CANONICAL.get(canonical)
    if drug is None:
        return ()
    return _molecule_product(drug).cautions


def age_band(canonical: str) -> tuple[int | None, int | None]:
    """``(min_age, max_age)`` for a molecule; ``None`` means no band."""
    drug = taxonomy.BY_CANONICAL.get(canonical)
    if drug is None:
        return None, None
    product = _molecule_product(drug)
    return product.age_min, product.age_max


def age_conflicts(canonical: str, age_years: int) -> str | None:
    """Reason key when this age is outside the molecule's verified band.

    Returns ``"child"`` / ``"elderly"``, or ``None`` when the age is inside the
    band (or the molecule has none).  Deliberately conservative: a band only
    exists where the Indian label or a guideline actually states one.
    """
    minimum, maximum = age_band(canonical)
    if minimum is not None and age_years < minimum:
        return "child"
    if maximum is not None and age_years >= maximum:
        return "elderly"
    return None


def catalogue() -> list[dict]:
    """Public, patient-free catalogue for ``GET /knowledge.json``.

    Brand first, then the molecules that only exist at molecule level, so a
    pharmacist can look up "Amaryl" and "glimepiride" and get the same facts.
    """
    from . import i18n  # local import: i18n imports schemas, not this module

    entries: list[dict] = []
    seen: set[str] = set()

    for product in PRODUCTS:
        seen.add(product.brand)
        entries.append(_entry(product, i18n))
    for drug in taxonomy.all_drugs():
        product = _molecule_product(drug)
        if product.brand in seen:
            continue
        seen.add(product.brand)
        entries.append(_entry(product, i18n))
    return entries


def _entry(product: Product, i18n) -> dict:  # noqa: ANN001 - local module handle
    molecules = []
    for canonical in product.molecules:
        drug = taxonomy.BY_CANONICAL.get(canonical)
        if drug is None:
            continue
        molecules.append(
            {
                "canonical": drug.canonical,
                "name_en": drug.name_en,
                "name_ml": drug.name_ml,
                "name_hi": drug.name_hi,
                "drug_class": drug.drug_class,
            }
        )
    return {
        "brand": product.brand,
        "form": product.form,
        "molecules": molecules,
        "strengths": [
            {"canonical": c, "strength_mg": s} for c, s in product.strengths
        ],
        "cautions": [
            {
                "key": key,
                "text": {
                    lang: i18n.t(f"kb.caution.{key}", lang)
                    for lang in ("en", "ml", "hi")
                },
            }
            for key in product.cautions
        ],
        "age_min": product.age_min,
        "age_max": product.age_max,
        "note": product.note,
    }
