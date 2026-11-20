"""Verified Indian drug taxonomy (molecule + common brand aliases).

Scope
-----
This is the curated subset the Kochi pilot needs: the molecules that actually
appear on pharmacy shelves in Kerala, with the brand names printed on the
strips (Dolo/Crocin/Calpol, Telma/Telsartan, Glycomet, Pan 40 ...).

The table is intentionally **data only** -- no logic -- so it can be replaced
by a licensed CDSCO/Aprilia-style feed later without touching the engine.

Strengths are the common Indian pack strengths in mg (levothyroxine is in
micrograms and is handled as mcg by the UI label set).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Drug:
    canonical: str
    name_en: str
    name_ml: str
    name_hi: str
    drug_class: str
    #: Usual Indian pack strength in mg (or mcg for levothyroxine).
    default_strength: float | None
    #: Adult daily ceiling in mg, where a hard ceiling exists.
    daily_max_mg: float | None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    #: True when the molecule is a combination partner that is rarely sold
    #: alone (e.g. HCTZ in Telma-H) -- still a duplicate-salt risk.
    combo_partner: bool = False


_DRUGS: tuple[Drug, ...] = (
    # -- Analgesics / antipyretics -----------------------------------------
    Drug(
        "paracetamol", "Paracetamol", "പാരസെറ്റമോൾ", "पैरासिटामोल",
        "paracetamol", 650, 4000,
        ("acetaminophen", "dolo", "dolo 650", "dolo650", "crocin", "calpol",
         "pacimol", "metacin", "paracip", "sumo", "fepanil", "p 650"),
    ),
    Drug(
        "ibuprofen", "Ibuprofen", "ഐബുപ്രോഫെൻ", "आइबुप्रोफेन",
        "nsaid", 400, 2400,
        ("brufen", "ibuflamar", "ibugesic", "flexon"),
    ),
    Drug(
        "aceclofenac", "Aceclofenac", "അസിക്ലോഫെനാക്", "एसिक्लोफेनाक",
        "nsaid", 100, 200,
        ("zerodol", "zerodol-p", "hifenac", "acenac", "zix"),
    ),
    Drug(
        "diclofenac", "Diclofenac", "ഡൈക്ലോഫെനാക്", "डाइक्लोफेनाक",
        "nsaid", 50, 150,
        ("voveran", "diclomol", "dynapar", "diclofenac sodium"),
    ),
    Drug(
        "naproxen", "Naproxen", "നാപ്രോക്സെൻ", "नेप्रोक्सेन",
        "nsaid", 500, 1250,
        ("naprosyn", "napra"), 
    ),
    Drug(
        "tramadol", "Tramadol", "ട്രാമഡോൾ", "ट्रामाडोल",
        "opioid", 50, 400,
        ("tramal", "ultracet", "tramazac", "domadol"),
    ),
    Drug(
        "aspirin", "Aspirin", "ആസ്പിരിൻ", "एस्पिरिन",
        "antiplatelet", 75, 4000,
        ("ecosprin", "loprin", "loprin 75", "disprin", "aspirin 75",
         "acetylsalicylic acid"),
    ),
    # -- Cardiovascular ----------------------------------------------------
    Drug(
        "telmisartan", "Telmisartan", "ടെൽമിസാർട്ടൻ", "टेल्मिसार्टन",
        "arb", 40, 160,
        ("telma", "telma 40", "telsartan", "telmikind", "telma-h", "telma h"),
    ),
    Drug(
        "losartan", "Losartan", "ലോസാർട്ടൻ", "लोसार्टन",
        "arb", 50, 100,
        ("losar", "losakind", "repace"), 
    ),
    Drug(
        "ramipril", "Ramipril", "റാമിപ്രിൽ", "रामिप्रिल",
        "acei", 5, 10,
        ("cardace", "ramiril", "hopace"),
    ),
    Drug(
        "enalapril", "Enalapril", "എനാലാപ്രിൽ", "एनालाप्रिल",
        "acei", 5, 40,
        ("envas", "enalapril maleate"),
    ),
    Drug(
        "hydrochlorothiazide", "Hydrochlorothiazide", "ഹൈഡ്രോക്ലോറോത്തയാസൈഡ്",
        "हाइड्रोक्लोरोथियाजाइड", "thiazide", 12.5, 50,
        ("hctz", "hydrochlorothiazide", "thiazide", "hcz"),
        combo_partner=True,
    ),
    Drug(
        "amlodipine", "Amlodipine", "അംലോഡിപിൻ", "एम्लोडिपिन",
        "ccb", 5, 10,
        ("amlopres", "stamlo", "amlokind", "amlovas", "amlong"),
    ),
    Drug(
        "metoprolol", "Metoprolol", "മെട്ടോപ്രോലോൾ", "मेटोप्रोलोल",
        "beta_blocker", 50, 400,
        ("metolar", "betaloc", "metolar-xr", "mepro"), 
    ),
    Drug(
        "atenolol", "Atenolol", "അറ്റെനോലോൾ", "एटेनोलोल",
        "beta_blocker", 50, 100,
        ("aten", "tenormin", "aten 50"), 
    ),
    Drug(
        "atorvastatin", "Atorvastatin", "അറ്റോർവാസ്റ്റാറ്റിൻ", "एटोर्वास्टेटिन",
        "statin", 10, 80,
        ("atorva", "storvas", "atorlip", "atorfit"), 
    ),
    Drug(
        "rosuvastatin", "Rosuvastatin", "റോസുവാസ്റ്റാറ്റിൻ", "रोसुवास्टेटिन",
        "statin", 10, 40,
        ("rosuvas", "rosuson", "crestor"), 
    ),
    Drug(
        "isosorbide_mononitrate", "Isosorbide mononitrate", "ഐസോസോർബൈഡ് മോണോനൈട്രേറ്റ്",
        "आइसोसॉर्बाइड मोनोनाइट्रेट", "nitrate", 30, 120,
        ("imdur", "monotrate", "isomonit", "ismo"), 
    ),
    Drug(
        "spironolactone", "Spironolactone", "സ്പൈറോണോലാക്ടോൺ", "स्पाइरोनोलैक्टोन",
        "diuretic_k_sparing", 25, 100,
        ("aldactone", "spiromide"), 
    ),
    Drug(
        "furosemide", "Furosemide", "ഫ്യൂറോസെമൈഡ്", "फ्यूरोसेमाइड",
        "diuretic_loop", 40, 160,
        ("lasix", "frusemide", "lasix 40"), 
    ),
    # -- Diabetes ----------------------------------------------------------
    Drug(
        "metformin", "Metformin", "മെറ്റ്ഫോർമിൻ", "मेटफॉर्मिन",
        "biguanide", 500, 3000,
        ("glycomet", "gluconorm", "okamet", "metfor", "glycomet-gp"),
    ),
    Drug(
        "glimepiride", "Glimepiride", "ഗ്ലിമെപിറൈഡ്", "ग्लिमेपिराइड",
        "sulfonylurea", 2, 8,
        ("amaryl", "glimestar", "glimy", "glimestar-m"), 
    ),
    Drug(
        "gliclazide", "Gliclazide", "ഗ്ലിക്ലാസൈഡ്", "ग्लिक्लाजाइड",
        "sulfonylurea", 80, 240,
        ("diamicron", "gliclaz"), 
    ),
    Drug(
        "sitagliptin", "Sitagliptin", "സിറ്റാഗ്ലിപ്റ്റിൻ", "सिटाग्लिप्टिन",
        "dpp4", 100, 100,
        ("januvia", "istavel", "sitaglip"), 
    ),
    Drug(
        "vildagliptin", "Vildagliptin", "വിൽഡാഗ്ലിപ്റ്റിൻ", "विल्डाग्लिप्टिन",
        "dpp4", 50, 100,
        ("galvus", "jalra", "vildaglip"), 
    ),
    # -- GI ----------------------------------------------------------------
    Drug(
        "pantoprazole", "Pantoprazole", "പാന്റോപ്രസോൾ", "पैंटोप्राज़ोल",
        "ppi", 40, 80,
        ("pan 40", "pan40", "pantocid", "pantop", "pan-d"), 
    ),
    Drug(
        "omeprazole", "Omeprazole", "ഓമെപ്രസോൾ", "ओमेप्राज़ोल",
        "ppi", 20, 40,
        ("omez", "ocid", "o capsule", "omeprazole 20"), 
    ),
    Drug(
        "rabeprazole", "Rabeprazole", "റാബെപ്രസോൾ", "रैबेप्राज़ोल",
        "ppi", 20, 40,
        ("razo", "rablet", "rabium"), 
    ),
    Drug(
        "domperidone", "Domperidone", "ഡോംപെരിഡോൺ", "डोम्पेरिडोन",
        "prokinetic", 10, 30,
        ("domstal", "vomistop", "domperidone 10"), 
    ),
    Drug(
        "ondansetron", "Ondansetron", "ഒൻഡാൻസെട്രോൺ", "ओंडान्सेट्रॉन",
        "antiemetic", 4, 16,
        ("emeset", "vomikind", "ondem", "ondansetron 4"), 
    ),
    # -- Respiratory / allergy --------------------------------------------
    Drug(
        "cetirizine", "Cetirizine", "സെറ്റിരിസിൻ", "सेटिरिज़िन",
        "antihistamine", 10, 10,
        ("cetzine", "alerid", "zyrtec", "cetiriz"), 
    ),
    Drug(
        "levocetirizine", "Levocetirizine", "ലെവോസെറ്റിരിസിൻ", "लेवोसेटिरिज़िन",
        "antihistamine", 5, 5,
        ("levocet", "xyzal", "levocetirizine 5", "montair-lc"),
    ),
    Drug(
        "montelukast", "Montelukast", "മോണ്ടെലൂകാസ്റ്റ്", "मोंटेलुकास्ट",
        "leukotriene", 10, 10,
        ("montair", "montair-lc", "montek", "montina"), 
    ),
    Drug(
        "salbutamol", "Salbutamol", "സാൽബ്യൂട്ടമോൾ", "सालब्युटामोल",
        "bronchodilator", 2, 16,
        ("asthalin", "ventorlin", "salbutamol 2"), 
    ),
    # -- Anti-infectives ---------------------------------------------------
    Drug(
        "amoxicillin", "Amoxicillin", "അമോക്സിസിലിൻ", "अमोक्सिसिलिन",
        "penicillin", 500, 3000,
        ("mox", "novamox", "amoxil", "moxikind-cv"),
    ),
    Drug(
        "clavulanic_acid", "Clavulanic acid", "ക്ലാവുലാനിക് ആസിഡ്", "क्लैवुलैनिक एसिड",
        "beta_lactamase_inhibitor", 125, None,
        ("clavam", "augmentin", "moxikind-cv", "clavulanate"),
        combo_partner=True,
    ),
    Drug(
        "azithromycin", "Azithromycin", "അസിത്രോമൈസിൻ", "एज़िथ्रोमाइसिन",
        "macrolide", 500, 500,
        ("azee", "azithral", "zithromax", "azee 500"), 
    ),
    Drug(
        "ciprofloxacin", "Ciprofloxacin", "സിപ്രോഫ്ലോക്സാസിൻ", "सिप्रोफ्लोक्सासिन",
        "fluoroquinolone", 500, 1500,
        ("ciprolet", "ciflox", "ciplox", "cifran"), 
    ),
    Drug(
        "ofloxacin", "Ofloxacin", "ഓഫ്ലോക്സാസിൻ", "ओफ्लोक्सासिन",
        "fluoroquinolone", 200, 800,
        ("o2", "zoxin", "oflox", "ofloxacin 200"), 
    ),
    Drug(
        "metronidazole", "Metronidazole", "മെട്രോനിഡാസോൾ", "मेट्रोनिडाज़ोल",
        "nitroimidazole", 400, 1200,
        ("flagyl", "metrogyl", "metron", "metronidazole 400"), 
    ),
    Drug(
        "doxycycline", "Doxycycline", "ഡോക്സിസൈക്ലിൻ", "डॉक्सीसाइक्लिन",
        "tetracycline", 100, 200,
        ("doxy", "microdox", "doxy 1"), 
    ),
    # -- Endocrine / other -------------------------------------------------
    Drug(
        "levothyroxine", "Levothyroxine", "ലെവോതൈറോക്സിൻ", "लेवोथायरॉक्सिन",
        "thyroid_hormone", 50, 200,
        ("thyronorm", "eltroxin", "thyrox", "thyronorm 50"), 
    ),
    Drug(
        "prednisolone", "Prednisolone", "പ്രെഡ്നിസോലോൺ", "प्रेड्निसोलोन",
        "corticosteroid", 10, 60,
        ("wysolone", "omnacortil", "predmet"), 
    ),
    Drug(
        "warfarin", "Warfarin", "വാർഫാരിൻ", "वॉरफ़ारिन",
        "anticoagulant", 5, 10,
        ("warf", "uniwarfin", "warf 5", "coumadin"), 
    ),
    Drug(
        "clopidogrel", "Clopidogrel", "ക്ലോപിഡോഗ്രെൽ", "क्लोपिडोग्रेल",
        "antiplatelet", 75, 75,
        ("clopilet", "deplatt", "plavix", "clopidogrel 75"), 
    ),
    Drug(
        "sertraline", "Sertraline", "സെർട്രാലിൻ", "सर्ट्रालिन",
        "ssri", 50, 200,
        ("daxid", "zosert", "sertima"), 
    ),
    Drug(
        "alprazolam", "Alprazolam", "അൽപ്രാസോളം", "अल्प्राज़ोलम",
        "benzodiazepine", 0.5, 4,
        ("alprax", "restyl", "trika"), 
    ),
    Drug(
        "sildenafil", "Sildenafil", "സിൽഡെനാഫിൽ", "सिल्डेनाफिल",
        "pde5", 50, 100,
        ("manforce", "penegra", "suhagra", "viagra"), 
    ),
)

# ---------------------------------------------------------------------------
# Fixed combinations printed as one brand name on the strip
# ---------------------------------------------------------------------------

_COMBOS: dict[str, tuple[tuple[str, float], ...]] = {
    "telma-h": (("telmisartan", 40), ("hydrochlorothiazide", 12.5)),
    "telma h": (("telmisartan", 40), ("hydrochlorothiazide", 12.5)),
    "telma-h 40": (("telmisartan", 40), ("hydrochlorothiazide", 12.5)),
    "combiflam": (("ibuprofen", 400), ("paracetamol", 325)),
    "montair-lc": (("montelukast", 10), ("levocetirizine", 5)),
    "montair lc": (("montelukast", 10), ("levocetirizine", 5)),
    "zerodol-sp": (("aceclofenac", 100), ("paracetamol", 325)),
    "zerodol sp": (("aceclofenac", 100), ("paracetamol", 325)),
    "augmentin": (("amoxicillin", 500), ("clavulanic_acid", 125)),
    "clavam": (("amoxicillin", 500), ("clavulanic_acid", 125)),
    "moxikind-cv": (("amoxicillin", 500), ("clavulanic_acid", 125)),
    "ultracet": (("tramadol", 37.5), ("paracetamol", 325)),
    "glycomet-gp": (("metformin", 500), ("glimepiride", 1)),
    "glimestar-m": (("glimepiride", 1), ("metformin", 500)),
    "pan-d": (("pantoprazole", 40), ("domperidone", 30)),
}

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

BY_CANONICAL: dict[str, Drug] = {d.canonical: d for d in _DRUGS}

#: alias -> canonical.  Longest alias wins at lookup time.
_ALIASES: dict[str, str] = {}
for _drug in _DRUGS:
    for _alias in (_drug.canonical, _drug.name_en.lower(), *_drug.aliases):
        _ALIASES.setdefault(_alias.lower().strip(), _drug.canonical)

_ALIAS_KEYS_BY_LENGTH = sorted(_ALIASES, key=len, reverse=True)

#: Three-letter brand aliases are common on Indian strips ("Mox 500", "Pan 40")
#: but short English words would match everything, so they are matched only as
#: standalone tokens and never when they are ordinary strip boilerplate.
_SHORT_ALIAS_MIN = 3
_SHORT_ALIAS_STOPWORDS = frozenset(
    {"pan", "tab", "cap", "the", "and", "for", "use", "day", "mg", "ml", "new", "max"}
)

#: Strip noise that must not survive normalisation.  Order matters.
_NOISE = re.compile(
    r"\b(tab(let)?s?|cap(sule)?s?|syr(up)?|inj(ection)?|sr|xr|cr|er|mr|"
    r"ip|lp|bp|usp|forte|ds|plus|film coated|extended release|"
    r"mfd|mfg|exp|batch|lot|mrp|rs|inclusive|taxes|store|below|temperature|"
    r"keep out of reach|of children|not for|sale|prescription|only)\b",
    re.IGNORECASE,
)
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu)\b", re.IGNORECASE)


def normalise(text: str) -> str:
    """Lowercase, drop strip boilerplate (barcodes, MRP, dosage forms)."""
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9\u0D00-\u0D7F\u0900-\u097F\s\-]", " ", lowered)
    lowered = _NOISE.sub(" ", lowered)
    return " ".join(lowered.split())


def parse_strength(text: str) -> float | None:
    """Return the first plausible strength in mg found in a strip line."""
    for match in _STRENGTH.finditer(text):
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit == "mcg":
            return value / 1000.0
        if unit == "g":
            return value * 1000.0
        if unit in {"ml", "iu"}:
            continue
        return value
    return None


def lookup(text: str) -> tuple[Drug, ...]:
    """Resolve a strip label to one or more molecules.

    Order of confidence:
    1. exact fixed-combination brand ("Telma-H") -> both molecules
    2. alias substring hit, longest alias first ("dolo 650" beats "dolo")
    3. fuzzy match on the cleaned label (>= 0.86) for OCR slips
       ("paracetamol" -> "paracetamo1", "telmisartan" -> "telmisarfan")
    """
    cleaned = normalise(text)
    if not cleaned:
        return ()

    for combo_key, members in _COMBOS.items():
        if combo_key in cleaned:
            hits = tuple(BY_CANONICAL[c] for c, _ in members)
            return hits

    found: list[Drug] = []
    for alias in _ALIAS_KEYS_BY_LENGTH:
        if len(alias) < _SHORT_ALIAS_MIN:
            continue
        if len(alias) < 4 and alias in _SHORT_ALIAS_STOPWORDS:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", cleaned):
            canonical = _ALIASES[alias]
            if all(d.canonical != canonical for d in found):
                found.append(BY_CANONICAL[canonical])

    if found:
        return tuple(found)

    # Fuzzy fallback, token by token.
    tokens = [t for t in cleaned.split() if len(t) >= 6]
    for token in tokens:
        match = difflib.get_close_matches(token, _ALIAS_KEYS_BY_LENGTH, n=1, cutoff=0.86)
        if match:
            canonical = _ALIASES[match[0]]
            return (BY_CANONICAL[canonical],)
    return ()


def combo_members(text: str) -> tuple[tuple[str, float], ...]:
    """Return the fixed-combination strengths for a brand, if any."""
    cleaned = normalise(text)
    for combo_key, members in _COMBOS.items():
        if combo_key in cleaned:
            return members
    return ()


def all_drugs() -> tuple[Drug, ...]:
    return _DRUGS


# ---------------------------------------------------------------------------
# LASA: look-alike and sound-alike brand handling
# ---------------------------------------------------------------------------

#: Brand tokens that collide when spoken at a busy pharmacy counter but have
#: nothing to do with each other chemically. Deliberately tiny and curated --
#: a wrong LASA entry is worse than a missing one. Each pair maps a token to the
#: *other* brand's display name, so a single-strip scan can still say
#: "careful, this sounds like X".
LASA_SOUND_ALIKE: dict[frozenset[str], dict[str, str]] = {
    # glimepiride vs amlodipine
    frozenset({"amaryl", "amlopres"}): {"amaryl": "Amlopres", "amlopres": "Amaryl"},
    # metronidazole vs metoprolol
    frozenset({"metrogyl", "metolar"}): {"metrogyl": "Metolar", "metolar": "Metrogyl"},
}

#: Suffixes that turn one brand into a different product (the pharmacy-shelf
#: trap: Telma / Telma-H, Pan 40 / Pan-D, Zerodol / Zerodol-SP).
_SKU_SUFFIXES = (
    "-plus", "-forte", "-xr", "-sr", "-sp", "-lc", "-gp", "-cv", "-ds",
    "-at", "-ct", "-ls", "-h", "-d", "-m",
)

#: Products we recognise by name but deliberately do **not** map to a molecule.
#: Loprin-LS is a real shelf neighbour of Loprin, but we have no verified
#: composition for it; claiming one would be worse than a "check the foil"
#: LASA alert. These still participate in LASA comparison.
BRAND_ONLY: dict[str, str] = {
    "loprin-ls": "Loprin-LS",
}


def knows_brand(label: str) -> bool:
    """True when the label matches a brand we recognise but do not resolve."""
    cleaned = normalise(label)
    return any(brand in cleaned for brand in BRAND_ONLY)


def brand_display(label: str) -> str:
    """Canonical display name for a brand-only product."""
    cleaned = normalise(label)
    for brand, display in BRAND_ONLY.items():
        if brand in cleaned:
            return display
    return label


def brand_token(label: str) -> str:
    """The first word of a strip label, digits stripped ('pan-d' -> 'pan-d')."""
    cleaned = normalise(label)
    first = cleaned.split(" ")[0] if cleaned else ""
    return re.sub(r"[^a-z]+", "", first)


def brand_root(label: str) -> str:
    """Brand family without its SKU suffix ('telma-h 40' -> 'telma').

    Used to spot the shelf confusion where two boxes share a family name but
    hold different molecules. Returns ``""`` when nothing usable is left.
    """
    cleaned = normalise(label)
    if not cleaned:
        return ""
    raw = cleaned.split(" ")[0]
    # Only a *hyphenated* suffix is an SKU marker. Without this, 'clavam'
    # would collapse to 'clava' because it ends in 'm'.
    for suffix in _SKU_SUFFIXES:
        if raw.endswith(suffix) and len(raw) - len(suffix) >= 3:
            return raw[: -len(suffix)].replace("-", "")
    return re.sub(r"[^a-z]", "", raw)
