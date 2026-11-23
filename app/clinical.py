"""Deterministic clinical guardrails.

Everything here is a pure function over resolved ingredients.  No model output,
no network call, no randomness: the same input always produces the same verdict,
which is what makes the warning auditable and testable.

Checks, in order of clinical priority:

1. ``DUPLICATE_SALT``   -- the same molecule across two strips (dual paracetamol).
2. ``PARACETAMOL_MAX``  -- cumulative daily paracetamol > 4000 mg.
3. ``INTERACTION``      -- curated molecule-pair table (bleeding, hyperkalaemia,
                           nitrate + PDE5, serotonin syndrome, ...).
4. ``DUPLICATE_CLASS``  -- two different molecules of one therapeutic family
                           (two NSAIDs, two ARBs, two sulfonylureas).
5. ``BATCH_AUDIT``      -- recall, expiry and cold-chain checks on the *box*
                           (``app.recall``), not the combination.
6. ``UNRECOGNISED``     -- anything the taxonomy could not verify.
7. ``SAFE``             -- nothing found; still not a prescription check.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from . import i18n, recall, taxonomy
from .schemas import (
    Finding,
    ResolvedIngredient,
    SafetyReport,
    ScannedMedicine,
    Severity,
    SpeechPayload,
    Verdict,
    Language,
    LanguageText,
)

PARACETAMOL_CANONICAL = "paracetamol"
PARACETAMOL_DAILY_MAX_MG = 4000.0
PARACETAMOL_WARN_MG = 3000.0  # soft ceiling: stagger doses above this

#: (molecule A, molecule B) -> (finding weight, risk key).
#: Weight 2 = hard contraindication, 1 = needs pharmacist review.
INTERACTIONS: dict[frozenset[str], tuple[int, str]] = {
    frozenset({"warfarin", "aspirin"}): (2, "bleeding"),
    frozenset({"warfarin", "clopidogrel"}): (2, "bleeding"),
    frozenset({"warfarin", "ibuprofen"}): (2, "gi_bleed"),
    frozenset({"warfarin", "diclofenac"}): (2, "gi_bleed"),
    frozenset({"warfarin", "aceclofenac"}): (2, "gi_bleed"),
    frozenset({"warfarin", "naproxen"}): (2, "gi_bleed"),
    frozenset({"clopidogrel", "omeprazole"}): (1, "reduced_efficacy"),
    frozenset({"clopidogrel", "rabeprazole"}): (1, "reduced_efficacy"),
    frozenset({"aspirin", "ibuprofen"}): (1, "gi_bleed"),
    frozenset({"aspirin", "diclofenac"}): (1, "gi_bleed"),
    frozenset({"prednisolone", "ibuprofen"}): (1, "gi_bleed"),
    frozenset({"prednisolone", "diclofenac"}): (1, "gi_bleed"),
    frozenset({"prednisolone", "aceclofenac"}): (1, "gi_bleed"),
    frozenset({"prednisolone", "naproxen"}): (1, "gi_bleed"),
    frozenset({"ramipril", "spironolactone"}): (1, "hyperkalemia"),
    frozenset({"enalapril", "spironolactone"}): (1, "hyperkalemia"),
    frozenset({"telmisartan", "spironolactone"}): (1, "hyperkalemia"),
    frozenset({"losartan", "spironolactone"}): (1, "hyperkalemia"),
    frozenset({"ramipril", "telmisartan"}): (2, "dual_blockade"),
    frozenset({"enalapril", "telmisartan"}): (2, "dual_blockade"),
    frozenset({"ramipril", "losartan"}): (2, "dual_blockade"),
    frozenset({"isosorbide_mononitrate", "sildenafil"}): (2, "severe_hypotension"),
    frozenset({"tramadol", "sertraline"}): (1, "serotonin"),
    frozenset({"glimepiride", "sertraline"}): (1, "hypoglycemia"),
    frozenset({"metoprolol", "atenolol"}): (1, "bradycardia"),
    frozenset({"glimepiride", "gliclazide"}): (1, "hypoglycemia"),
    frozenset({"telmisartan", "furosemide"}): (1, "hypotension"),
    frozenset({"losartan", "furosemide"}): (1, "hypotension"),
    frozenset({"amlodipine", "sildenafil"}): (1, "hypotension"),
}

#: Classes where holding two different molecules at once is a real hazard.
DUPLICATE_CLASS_HAZARD: set[str] = {
    "nsaid", "arb", "acei", "statin", "sulfonylurea", "ppi",
    "antihistamine", "beta_blocker", "nitrate", "pde5",
    "diuretic_k_sparing", "fluoroquinolone",
}


@dataclass
class _Occurrence:
    """One molecule as it appears on one strip."""

    ingredient: ResolvedIngredient
    strip_index: int
    strength_mg: float | None


def _flatten(medicines: list[ScannedMedicine]) -> list[_Occurrence]:
    occurrences: list[_Occurrence] = []
    for index, medicine in enumerate(medicines):
        for ingredient in medicine.ingredients:
            occurrences.append(
                _Occurrence(
                    ingredient=ingredient,
                    strip_index=index,
                    strength_mg=ingredient.strength_mg,
                )
            )
    return occurrences


def _name(ingredient: ResolvedIngredient, lang: str) -> str:
    return {
        "en": ingredient.name_en,
        "ml": ingredient.name_ml,
        "hi": ingredient.name_hi,
    }[lang]


def _duplicate_salt_findings(occurrences: list[_Occurrence]) -> list[Finding]:
    by_salt: dict[str, list[_Occurrence]] = defaultdict(list)
    for occurrence in occurrences:
        by_salt[occurrence.ingredient.canonical].append(occurrence)

    findings: list[Finding] = []
    for canonical, items in by_salt.items():
        distinct_strips = {item.strip_index for item in items}
        if len(distinct_strips) < 2:
            continue  # one strip mentioning a molecule twice is not a duplicate

        strengths = [i.strength_mg for i in items if i.strength_mg]
        single = max(strengths) if strengths else 0.0
        total = sum(strengths) if strengths else 0.0
        ingredient = items[0].ingredient

        # Paracetamol duplication is life-threatening, everything else is a
        # strong warning -- both are surfaced, severity differs.
        severity = Severity.critical
        findings.append(
            Finding(
                code="DUPLICATE_SALT",
                severity=severity,
                title=i18n.language_text(
                    "dup_salt.title"
                ),
                message=LanguageText(
                    **{
                        lang: i18n.t(
                            "dup_salt.body", lang,
                            name=_name(ingredient, lang),
                            count=len(distinct_strips),
                            total=total,
                            single=single,
                        )
                        for lang in ("en", "ml", "hi")
                    }
                ),
                action=i18n.language_text("dup_salt.action"),
                anchors=[canonical],
            )
        )
    return findings


def _paracetamol_findings(
    occurrences: list[_Occurrence], taken_today_mg: float
) -> list[Finding]:
    per_strip: dict[int, float] = defaultdict(float)
    has_paracetamol = False
    name_source: ResolvedIngredient | None = None

    for occurrence in occurrences:
        if occurrence.ingredient.canonical != PARACETAMOL_CANONICAL:
            continue
        has_paracetamol = True
        name_source = name_source or occurrence.ingredient
        per_strip[occurrence.strip_index] += occurrence.strength_mg or 0.0

    if not has_paracetamol or name_source is None:
        return []

    # Worst case the user takes one tablet of every strip they scanned.
    scanned_total = sum(per_strip.values())
    projected = scanned_total + taken_today_mg

    def _message(key: str) -> LanguageText:
        return LanguageText(
            **{
                lang: i18n.t(
                    key, lang, name=_name(name_source, lang), total=projected
                )
                for lang in ("en", "ml", "hi")
            }
        )

    if projected > PARACETAMOL_DAILY_MAX_MG:
        return [
            Finding(
                code="PARACETAMOL_DAILY_MAX",
                severity=Severity.critical,
                title=i18n.language_text("para_max.title"),
                message=_message("para_max.body"),
                action=i18n.language_text("para_max.action"),
                anchors=[PARACETAMOL_CANONICAL],
            )
        ]
    if projected >= PARACETAMOL_WARN_MG:
        return [
            Finding(
                code="PARACETAMOL_NEAR_MAX",
                severity=Severity.warning,
                title=i18n.language_text("para_near.title"),
                message=_message("para_near.body"),
                action=i18n.language_text("para_near.action"),
                anchors=[PARACETAMOL_CANONICAL],
            )
        ]
    return []


def _interaction_findings(occurrences: list[_Occurrence]) -> list[Finding]:
    present: dict[str, ResolvedIngredient] = {}
    for occurrence in occurrences:
        present.setdefault(occurrence.ingredient.canonical, occurrence.ingredient)

    findings: list[Finding] = []
    reported: set[frozenset[str]] = set()

    for pair, (weight, risk) in INTERACTIONS.items():
        if not pair <= set(present):
            continue
        if pair in reported:
            continue
        reported.add(pair)
        a_canonical, b_canonical = sorted(pair)
        a = present[a_canonical]
        b = present[b_canonical]
        risk_copy = i18n.risk_text(risk)

        findings.append(
            Finding(
                code="INTERACTION",
                severity=Severity.critical if weight == 2 else Severity.warning,
                title=i18n.language_text("interaction.title"),
                message=LanguageText(
                    en=i18n.t("interaction.body", "en",
                              a=a.name_en, b=b.name_en, risk_en=risk_copy["en"]),
                    ml=i18n.t("interaction.body", "ml",
                              a=a.name_ml, b=b.name_ml, risk_ml=risk_copy["ml"]),
                    hi=i18n.t("interaction.body", "hi",
                              a=a.name_hi, b=b.name_hi, risk_hi=risk_copy["hi"]),
                ),
                action=i18n.language_text("interaction.action"),
                anchors=[a_canonical, b_canonical],
            )
        )
    return findings


def _duplicate_class_findings(occurrences: list[_Occurrence]) -> list[Finding]:
    by_class: dict[str, dict[str, ResolvedIngredient]] = defaultdict(dict)
    for occurrence in occurrences:
        ingredient = occurrence.ingredient
        if ingredient.drug_class in DUPLICATE_CLASS_HAZARD:
            by_class[ingredient.drug_class].setdefault(ingredient.canonical, ingredient)

    findings: list[Finding] = []
    for drug_class, members in by_class.items():
        if len(members) < 2:
            continue
        a, b = list(members.values())[:2]
        # An ACEi + ARB pair is already reported as a hard interaction -- do
        # not repeat it as a weaker "same family" warning.
        if frozenset({a.canonical, b.canonical}) in INTERACTIONS:
            continue
        group = i18n.class_group(drug_class)
        findings.append(
            Finding(
                code="DUPLICATE_CLASS",
                severity=Severity.warning,
                title=i18n.language_text("class_dup.title"),
                message=LanguageText(
                    en=i18n.t("class_dup.body", "en", a=a.name_en, b=b.name_en,
                              group_en=group["en"]),
                    ml=i18n.t("class_dup.body", "ml", a=a.name_ml, b=b.name_ml,
                              group_ml=group["ml"]),
                    hi=i18n.t("class_dup.body", "hi", a=a.name_hi, b=b.name_hi,
                              group_hi=group["hi"]),
                ),
                action=i18n.language_text("class_dup.action"),
                anchors=[a.canonical, b.canonical],
            )
        )
    return findings


@dataclass(frozen=True)
class _LasaCandidate:
    """One scanned label, reduced to what a LASA check actually needs.

    Runs on the *labels* (what the user sees on the foil) rather than on
    molecule names, because the confusion happens at the counter, not in the
    molecule table.
    """

    label: str
    root: str
    token: str
    molecules: frozenset[str]

    @property
    def verified(self) -> bool:
        """True when the taxonomy resolved this label's molecules."""
        return bool(self.molecules)


def _lasa_candidates(medicines: list[ScannedMedicine]) -> list[_LasaCandidate]:
    """Keep every label a confusion check can compare.

    Brand-only products (Loprin-LS) take part too: we know the name, we just do
    not claim its composition, which is exactly what a LASA check needs.
    """
    candidates: list[_LasaCandidate] = []
    for medicine in medicines:
        if not medicine.matched and not medicine.brand_only:
            continue
        candidates.append(
            _LasaCandidate(
                label=medicine.label,
                root=taxonomy.brand_root(medicine.label),
                token=taxonomy.brand_token(medicine.label),
                molecules=frozenset(i.canonical for i in medicine.ingredients),
            )
        )
    return candidates


def _lasa_finding(body_key: str, a: str, b: str, anchors: list[str]) -> Finding:
    """One localised LASA advisory.

    Anchors are printed labels, not molecules: the chip must show what is
    written on the foil.
    """
    return Finding(
        code="LASA_RISK",
        severity=Severity.warning,
        title=i18n.language_text("lasa.title"),
        message=LanguageText(
            **{lang: i18n.t(body_key, lang, a=a, b=b) for lang in ("en", "ml", "hi")}
        ),
        action=i18n.language_text("lasa.action"),
        anchors=anchors,
    )


def _lasa_pair_body_key(a: _LasaCandidate, b: _LasaCandidate) -> str | None:
    """Copy key for a two-label collision, or ``None`` if the pair is not LASA.

    Rules, in order:

    * both sides unresolved -- nothing to compare (``UNRECOGNISED`` covers it);
    * identical contents -- not a confusion risk unless curated as one;
    * same brand family -- "different contents" only if both sides resolved,
      otherwise ask the user to verify;
    * curated sound-alike pair -- a collision even across brand families.
    """
    if not a.molecules and not b.molecules:
        return None

    sound_alike = frozenset({a.token, b.token}) in taxonomy.LASA_SOUND_ALIKE
    if a.molecules == b.molecules and not sound_alike:
        return None

    if a.root and a.root == b.root:
        return "lasa.body" if (a.molecules and b.molecules) else "lasa.body_verify"
    if sound_alike:
        return "lasa.body_sound"
    return None


def _dual_strip_lasa_findings(candidates: list[_LasaCandidate]) -> list[Finding]:
    """Strips scanned together that share a brand family or sound alike."""
    findings: list[Finding] = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            body_key = _lasa_pair_body_key(a, b)
            if body_key is None:
                continue
            findings.append(_lasa_finding(body_key, a.label, b.label, [a.label, b.label]))
    return findings


def _single_strip_lasa_findings(candidates: list[_LasaCandidate]) -> list[Finding]:
    """A lone strip whose printed name alone invites a mix-up at the counter.

    Only the curated sound-alike table applies here: a brand family needs two
    boxes, so firing on a single strip would be a false alarm on every Telma
    scan.
    """
    present_tokens = {candidate.token for candidate in candidates}

    findings: list[Finding] = []
    for candidate in candidates:
        for pair, partners in taxonomy.LASA_SOUND_ALIKE.items():
            if candidate.token not in pair:
                continue
            if pair <= present_tokens:
                continue  # both sides present: the pairwise check already fired
            partner = partners.get(candidate.token)
            if not partner:
                continue
            findings.append(
                _lasa_finding(
                    "lasa.alone.body", candidate.label, partner, [candidate.label]
                )
            )
    return findings


def _lasa_findings(medicines: list[ScannedMedicine]) -> list[Finding]:
    """Run both LASA passes: deliberate pairs first, then lone-strip advisories."""
    candidates = _lasa_candidates(medicines)
    return _dual_strip_lasa_findings(candidates) + _single_strip_lasa_findings(candidates)


def _unknown_finding() -> Finding:
    return Finding(
        code="UNRECOGNISED_MEDICINE",
        severity=Severity.info,
        title=i18n.language_text("unknown.title"),
        message=i18n.language_text("unknown.body"),
        action=i18n.language_text("unknown.action"),
        anchors=[],
    )


def _safe_finding() -> Finding:
    return Finding(
        code="NO_DANGEROUS_OVERLAP",
        severity=Severity.info,
        title=i18n.language_text("safe.title"),
        message=i18n.language_text("safe.body"),
        action=i18n.language_text("safe.action"),
        anchors=[],
    )


def build_speech(findings: list[Finding], language: Language) -> SpeechPayload:
    """Read out at most the three most serious findings.

    Reading every finding aloud buries the one that matters.  We take the
    highest severities first, then the impact statement, then the action.
    """
    lang = language.value
    ordered = sorted(
        findings,
        key=lambda f: {Severity.critical: 0, Severity.warning: 1, Severity.info: 2}[f.severity],
    )
    spoken = [f for f in ordered if f.severity in (Severity.critical, Severity.warning)][:3]
    if not spoken:
        spoken = ordered[:1]

    joiner = i18n.t("speech_join", lang)
    parts = [
        f"{getattr(f.title, lang)}. {getattr(f.message, lang)} {getattr(f.action, lang)}"
        for f in spoken
    ]
    body = joiner.join(parts)
    text = f"{i18n.t('speech_intro', lang)} {body} {i18n.t('speech_outro', lang)}"
    return SpeechPayload(language=language, text=" ".join(text.split()))


def analyse(
    medicines: list[ScannedMedicine],
    language: Language,
    paracetamol_taken_today_mg: float = 0.0,
    as_of: date | None = None,
) -> SafetyReport:
    """Run every guardrail and return a localised, speakable report.

    ``as_of`` is only for the batch/expiry audit; it exists so tests and audits
    can pin the calendar instead of depending on the day they run.
    """
    occurrences = _flatten(medicines)

    findings: list[Finding] = []
    findings += _duplicate_salt_findings(occurrences)
    findings += _paracetamol_findings(occurrences, paracetamol_taken_today_mg)
    findings += _interaction_findings(occurrences)
    findings += recall.audit(medicines, as_of)
    findings += _duplicate_class_findings(occurrences)
    findings += _lasa_findings(medicines)

    unrecognised = [m for m in medicines if not m.matched]
    if unrecognised:
        findings.append(_unknown_finding())

    if not findings:
        findings.append(_safe_finding())

    # Verdict: the worst severity wins; unknown input cannot be called safe.
    if any(f.severity == Severity.critical for f in findings):
        verdict = Verdict.critical
    elif any(f.severity == Severity.warning for f in findings):
        verdict = Verdict.caution
    elif unrecognised and len(unrecognised) == len(medicines):
        verdict = Verdict.unknown
    elif unrecognised:
        verdict = Verdict.caution
    else:
        verdict = Verdict.safe

    return SafetyReport(
        verdict=verdict,
        findings=findings,
        speech=build_speech(findings, language),
    )


@dataclass(frozen=True)
class BasketReport:
    """Per-strip reports plus the combined verdict for a multi-strip scan."""

    per_strip: list[SafetyReport]
    combined: SafetyReport


def analyse_basket(
    strips: list[list[ScannedMedicine]],
    language: Language,
    paracetamol_taken_today_mg: float = 0.0,
) -> BasketReport:
    """Analyse each strip alone, then the whole basket as one set.

    The combined pass is not a concatenation of the per-strip verdicts: a
    duplicate salt, a duplicated drug class or a LASA pair usually only shows
    up when two strips meet. Per-strip reports exist so the UI can label which
    strip contributed what, not so they can be summed.
    """
    per_strip = [
        analyse(strip, language, paracetamol_taken_today_mg) for strip in strips
    ]
    everything = [medicine for strip in strips for medicine in strip]
    combined = analyse(everything, language, paracetamol_taken_today_mg)
    return BasketReport(per_strip=per_strip, combined=combined)
