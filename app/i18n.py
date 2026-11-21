"""Malayalam / Hindi / English copy for every safety finding.

Rules for the wording
---------------------
* Short sentences.  One idea each.  A 70-year-old reading a phone at arm's
  length must not have to parse a subordinate clause.
* Always say what to *do* ("both together do not take", "show the pharmacist"),
  never only what is wrong.
* Drug names stay in their transliterated form because that is what is printed
  on the strip the patient is holding.
* No abbreviations in ml/hi: "mg" is written out as "മില്ലിഗ്രാം" /
  "मिलीग्राम" once per sentence.
"""

from __future__ import annotations

from .schemas import Language, LanguageText

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

TEXTS: dict[str, dict[str, str]] = {
    # -- duplicate salt ----------------------------------------------------
    "dup_salt.title": {
        "en": "Same medicine twice",
        "ml": "ഒരേ മരുന്ന് രണ്ടുതവണ",
        "hi": "एक ही दवा दो बार",
    },
    "dup_salt.body": {
        "en": "{name} is present in {count} of these strips. Taking them together "
              "gives you {total:.0f} mg of {name} at once instead of {single:.0f} mg.",
        "ml": "{name} ഈ {count} സ്ട്രിപ്പുകളിലും ഉണ്ട്. രണ്ടും ഒരുമിച്ച് കഴിച്ചാൽ "
              "ഒറ്റത്തവണ {single:.0f} മില്ലിഗ്രാമിനു പകരം {total:.0f} മില്ലിഗ്രാം "
              "{name} ശരീരത്തിൽ ചെല്ലും.",
        "hi": "{name} इन {count} पत्तों में से हर एक में है। दोनों एक साथ लेने पर "
              "एक बार में {single:.0f} मिलीग्राम की जगह {total:.0f} मिलीग्राम "
              "{name} शरीर में जाएगी।",
    },
    "dup_salt.action": {
        "en": "Take only one of them. Keep the other strip aside.",
        "ml": "ഇവയിൽ ഒന്ന് മാത്രം കഴിക്കുക. മറ്റേ സ്ട്രിപ്പ് മാറ്റിവയ്ക്കുക.",
        "hi": "इनमें से सिर्फ़ एक लें। दूसरा पत्ता अलग रख दें।",
    },
    # -- paracetamol ceiling ----------------------------------------------
    "para_max.title": {
        "en": "Paracetamol over the daily limit",
        "ml": "പാരസെറ്റമോൾ ദിവസത്തെ പരിധി കവിയുന്നു",
        "hi": "पैरासिटामोल दैनिक सीमा से ज़्यादा",
    },
    "para_max.body": {
        "en": "{name} would reach {total:.0f} mg in a day. The adult limit is "
              "4000 mg. More than that can damage the liver, and the damage "
              "often starts without any pain.",
        "ml": "ഒരു ദിവസം {total:.0f} മില്ലിഗ്രാം {name} ആകും. മുതിർന്നവർക്ക് "
              "പരമാവധി 4000 മില്ലിഗ്രാം മാത്രം. അതിൽ കൂടുതൽ കരൾ നശിപ്പിക്കും. "
              "വേദന അനുഭവപ്പെടാതെയും കരൾ കേടാകാം.",
        "hi": "एक दिन में {total:.0f} मिलीग्राम {name} हो जाएगी। बड़ों के लिए "
              "सीमा 4000 मिलीग्राम है। इससे ज़्यादा लिवर को नुकसान पहुँचाता है, "
              "और नुकसान बिना दर्द के भी शुरू हो सकता है।",
    },
    "para_max.action": {
        "en": "Stop and ask a doctor or pharmacist today.",
        "ml": "നിർത്തി ഇന്നുതന്നെ ഡോക്ടറെയോ ഫാർമസിസ്റ്റിനെയോ കാണുക.",
        "hi": "रोकें और आज ही डॉक्टर या फार्मासिस्ट से पूछें।",
    },
    "para_near.title": {
        "en": "Paracetamol close to the limit",
        "ml": "പാരസെറ്റമോൾ പരിധിയോട് അടുത്ത്",
        "hi": "पैरासिटामोल सीमा के पास",
    },
    "para_near.body": {
        "en": "You are already at {total:.0f} mg of paracetamol for the day, "
              "against a limit of 4000 mg. Another dose may cross the line.",
        "ml": "ഇന്ന് ഇതുവരെ {total:.0f} മില്ലിഗ്രാം പാരസെറ്റമോൾ കഴിച്ചു. "
              "പരിധി 4000 മില്ലിഗ്രാം. അടുത്ത ഡോസ് പരിധി കവിയാം.",
        "hi": "आज अब तक {total:.0f} मिलीग्राम पैरासिटामोल ली है। सीमा 4000 "
              "मिलीग्राम है। अगली खुराक सीमा पार कर सकती है।",
    },
    "para_near.action": {
        "en": "Do not take another paracetamol tablet today without advice.",
        "ml": "ഉപദേശമില്ലാതെ ഇന്ന് വീണ്ടും പാരസെറ്റമോൾ കഴിക്കരുത്.",
        "hi": "सलाह के बिना आज और पैरासिटामोल न लें।",
    },
    # -- same class --------------------------------------------------------
    "class_dup.title": {
        "en": "Two medicines of the same type",
        "ml": "ഒരേ വിഭാഗത്തിൽപ്പെട്ട രണ്ട് മരുന്നുകൾ",
        "hi": "एक ही तरह की दो दवाएँ",
    },
    "class_dup.body": {
        "en": "{a} and {b} work the same way ({group_en}). Using both adds the "
              "side effects without adding much benefit.",
        "ml": "{a} എന്നതും {b} എന്നതും ഒരേ രീതിയിൽ പ്രവർത്തിക്കുന്നു ({group_ml}). "
              "രണ്ടും കൂടി കഴിച്ചാൽ ഗുണം കൂടാതെ പാർശ്വഫലങ്ങൾ കൂടും.",
        "hi": "{a} और {b} एक ही तरह काम करती हैं ({group_hi})। दोनों लेने से "
              "फ़ायदा बढ़े बिना साइड इफ़ेक्ट बढ़ेंगे।",
    },
    "class_dup.action": {
        "en": "Ask your doctor which one to continue.",
        "ml": "ഏത് തുടരണമെന്ന് ഡോക്ടറോട് ചോദിക്കുക.",
        "hi": "कौन-सी जारी रखनी है, डॉक्टर से पूछें।",
    },
    # -- interaction -------------------------------------------------------
    "interaction.title": {
        "en": "Dangerous combination",
        "ml": "അപകടകരമായ കൂടിച്ചേരൽ",
        "hi": "खतरनाक मेल",
    },
    "interaction.body": {
        "en": "{a} with {b}: {risk_en}",
        "ml": "{a} എന്നത് {b} എന്നതിനൊപ്പം: {risk_ml}",
        "hi": "{a} के साथ {b}: {risk_hi}",
    },
    "interaction.action": {
        "en": "Do not take them together. Call your doctor or pharmacist.",
        "ml": "ഇവ ഒരുമിച്ച് കഴിക്കരുത്. ഡോക്ടറെയോ ഫാർമസിസ്റ്റിനെയോ വിളിക്കുക.",
        "hi": "इन्हें साथ में न लें। डॉक्टर या फार्मासिस्ट को बताएँ।",
    },
    # -- LASA: look-alike / sound-alike ------------------------------------
    "lasa.title": {
        "en": "Look-alike medicine",
        "ml": "സമാനരൂപ മരുന്ന്",
        "hi": "मिलती-जुलती दवा",
    },
    "lasa.body": {
        "en": "{a} and {b} look almost the same on the strip, but they do not "
              "contain the same medicine. Confusing the two is a common reason "
              "for taking the wrong tablet.",
        "ml": "{a}, {b} എന്നിവ സ്ട്രിപ്പിൽ കാണാൻ ഒരുപോലെയാണ്. എന്നാൽ ഇവയിൽ "
              "അടങ്ങിയിരിക്കുന്ന മരുന്ന് ഒരുപോലെയല്ല. തെറ്റായ ഗുളിക കഴിക്കുന്നതിന്റെ "
              "പ്രധാന കാരണം ഇതാണ്.",
        "hi": "{a} और {b} पत्ते पर लगभग एक जैसी दिखती हैं, पर इनमें एक ही दवा "
              "नहीं है। गलत गोली लेने की यह आम वजह है।",
    },
    "lasa.body_sound": {
        "en": "{a} and {b} sound almost the same when the name is spoken aloud. "
              "At a busy counter the wrong box can be handed over.",
        "ml": "{a}, {b} എന്നിവ ഉച്ചരിക്കുമ്പോൾ ഒരുപോലെ തോന്നും. തിരക്കുള്ള "
              "കൗണ്ടറിൽ തെറ്റായ പെട്ടി കിട്ടാനുള്ള സാധ്യതയുണ്ട്.",
        "hi": "{a} और {b} बोलने में लगभग एक जैसी लगती हैं। भीड़ वाले काउंटर पर "
              "गलत डिब्बा मिल सकता है।",
    },
    "lasa.body_verify": {
        "en": "{a} and {b} are names that are easily mixed up at the counter, "
              "and they are not interchangeable. Check the printed name and "
              "strength on the foil before you take either one.",
        "ml": "{a}, {b} എന്നീ പേരുകൾ കൗണ്ടറിൽ എളുപ്പം തെറ്റിപ്പോകാം. ഇവ പരസ്പരം "
              "പകരം ഉപയോഗിക്കാനുള്ളതല്ല. ഏതെങ്കിലും എടുക്കുന്നതിന് മുൻപ് ഫോയിലിൽ "
              "അച്ചടിച്ച പേരും ശക്തിയും ഉറപ്പാക്കുക.",
        "hi": "{a} और {b} ऐसे नाम हैं जिनमें काउंटर पर गड़बड़ होना आम है, और ये "
              "एक-दूसरे की जगह नहीं ले सकतीं। कोई भी लेने से पहले फ़ॉइल पर छपा "
              "पूरा नाम और ताकत जाँचें।",
    },
    "lasa.alone.body": {
        "en": "{a} is easily mixed up with {b}, which is a different medicine. "
              "Read the full name and strength on the foil before you take it.",
        "ml": "{a} എന്നത് {b} എന്നതുമായി എളുപ്പം തെറ്റിപ്പോകാം. {b} വേറൊരു "
              "മരുന്നാണ്. കഴിക്കുന്നതിന് മുൻപ് ഫോയിലിൽ പൂർണ്ണനാമവും ശക്തിയും വായിക്കുക.",
        "hi": "{a} को {b} से आसानी से मिलाया जा सकता है, जो अलग दवा है। लेने से "
              "पहले फ़ॉइल पर पूरा नाम और ताकत पढ़ें।",
    },
    "lasa.action": {
        "en": "Read the full name on the foil, not just the colour. Keep the "
              "strips apart.",
        "ml": "നിറം മാത്രം നോക്കാതെ ഫോയിലിൽ അച്ചടിച്ച പൂർണ്ണനാമം വായിക്കുക. "
              "സ്ട്രിപ്പുകൾ വെവ്വേറെ സൂക്ഷിക്കുക.",
        "hi": "सिर्फ़ रंग नहीं, फ़ॉइल पर छपा पूरा नाम पढ़ें। पत्तों को अलग-अलग रखें।",
    },
    # -- unrecognised ------------------------------------------------------
    "unknown.title": {
        "en": "Could not read this strip",
        "ml": "ഈ സ്ട്രിപ്പ് വായിക്കാനായില്ല",
        "hi": "यह पत्ता पढ़ा नहीं जा सका",
    },
    "unknown.body": {
        "en": "We could not confirm the medicine on this strip, so we will not "
              "guess. A guess here could be dangerous.",
        "ml": "ഈ സ്ട്രിപ്പിലെ മരുന്ന് ഉറപ്പിക്കാനായില്ല. അതിനാൽ ഞങ്ങൾ ഊഹിക്കുന്നില്ല. "
              "തെറ്റായ ഊഹം അപകടമാകാം.",
        "hi": "इस पत्ते की दवा पक्की नहीं हो सकी, इसलिए हम अंदाज़ा नहीं लगाएँगे। "
              "ग़लत अंदाज़ा खतरनाक हो सकता है।",
    },
    "unknown.action": {
        "en": "Photograph the printed name clearly, or type it below.",
        "ml": "അച്ചടിച്ച പേര് വ്യക്തമായി ഫോട്ടോ എടുക്കുക, അല്ലെങ്കിൽ താഴെ ടൈപ്പ് ചെയ്യുക.",
        "hi": "छपा हुआ नाम साफ़ फ़ोटो लें, या नीचे टाइप करें।",
    },
    # -- safe --------------------------------------------------------------
    "safe.title": {
        "en": "No dangerous overlap found",
        "ml": "അപകടകരമായ ഇരട്ടിപ്പ് കണ്ടെത്തിയില്ല",
        "hi": "कोई खतरनाक दोहराव नहीं मिला",
    },
    "safe.body": {
        "en": "These strips do not repeat the same salt and we found no known "
              "dangerous pair among them.",
        "ml": "ഈ സ്ട്രിപ്പുകളിൽ ഒരേ ഘടകം ആവർത്തിക്കുന്നില്ല. അറിയപ്പെടുന്ന "
              "അപകടകരമായ കൂടിച്ചേരലും കണ്ടെത്തിയില്ല.",
        "hi": "इन पत्तों में एक ही तत्व दोहराया नहीं गया और कोई ज्ञात खतरनाक "
              "मेल भी नहीं मिला।",
    },
    "safe.action": {
        "en": "This is not a prescription check. Follow your doctor's advice.",
        "ml": "ഇത് കുറിപ്പടി പരിശോധനയല്ല. ഡോക്ടറുടെ നിർദ്ദേശം പാലിക്കുക.",
        "hi": "यह पर्चे की जाँच नहीं है। डॉक्टर की सलाह मानें।",
    },
    # -- misc --------------------------------------------------------------
    "disclaimer": {
        "en": "KathaPulse AI is a screening aid, not a diagnosis. Always confirm "
              "with a doctor or pharmacist.",
        "ml": "കഥാപൾസ് AI ഒരു സഹായ മുന്നറിയിപ്പ് മാത്രമാണ്, രോഗനിർണയമല്ല. "
              "എപ്പോഴും ഡോക്ടറെയോ ഫാർമസിസ്റ്റിനെയോ സ്ഥിരീകരിക്കുക.",
        "hi": "कथापल्स AI सिर्फ़ एक चेतावनी सहायक है, निदान नहीं। हमेशा डॉक्टर "
              "या फार्मासिस्ट से पुष्टि करें।",
    },
    "speech_intro": {
        "en": "KathaPulse warning.",
        "ml": "കഥാപൾസ് മുന്നറിയിപ്പ്.",
        "hi": "कथापल्स चेतावनी।",
    },
    "speech_join": {
        "en": " Next. ",
        "ml": " അടുത്തത്. ",
        "hi": " अगला। ",
    },
    "speech_outro": {
        "en": "For any doubt, ask your pharmacist.",
        "ml": "സംശയമുണ്ടെങ്കിൽ ഫാർമസിസ്റ്റിനോട് ചോദിക്കുക.",
        "hi": "कोई शंका हो तो फार्मासिस्ट से पूछें।",
    },
}

#: Plain-language names for drug classes, used inside class-duplicate findings.
CLASS_GROUP: dict[str, dict[str, str]] = {
    "nsaid": {"en": "painkiller of the same family", "ml": "ഒരേ കുടുംബത്തിലെ വേദനാസംഹാരി", "hi": "एक ही वर्ग की दर्द निवारक"},
    "arb": {"en": "blood pressure medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ രക്തസമ്മർദ്ദ മരുന്ന്", "hi": "एक ही वर्ग की ब्लड प्रेशर दवा"},
    "acei": {"en": "blood pressure medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ രക്തസമ്മർദ്ദ മരുന്ന്", "hi": "एक ही वर्ग की ब्लड प्रेशर दवा"},
    "statin": {"en": "cholesterol medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ കൊളസ്ട്രോൾ മരുന്ന്", "hi": "एक ही वर्ग की कोलेस्ट्रॉल दवा"},
    "sulfonylurea": {"en": "sugar-lowering medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ പഞ്ചസാര കുറയ്ക്കുന്ന മരുന്ന്", "hi": "एक ही वर्ग की शुगर कम करने वाली दवा"},
    "ppi": {"en": "acidity medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ അസിഡിറ്റി മരുന്ന്", "hi": "एक ही वर्ग की एसिडिटी दवा"},
    "antihistamine": {"en": "allergy medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ അലർജി മരുന്ന്", "hi": "एक ही वर्ग की एलर्जी दवा"},
    "beta_blocker": {"en": "heart-rate medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ ഹൃദയമിടിപ്പ് കുറയ്ക്കുന്ന മരുന്ന്", "hi": "एक ही वर्ग की धड़कन कम करने वाली दवा"},
    "nitrate": {"en": "chest-pain medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ നെഞ്ചുവേദന മരുന്ന്", "hi": "एक ही वर्ग की सीने के दर्द की दवा"},
    "pde5": {"en": "medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ മരുന്ന്", "hi": "एक ही वर्ग की दवा"},
    "biguanide": {"en": "sugar-lowering medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ പഞ്ചസാര കുറയ്ക്കുന്ന മരുന്ന്", "hi": "एक ही वर्ग की शुगर कम करने वाली दवा"},
    "dpp4": {"en": "sugar-lowering medicine of the same family", "ml": "ഒരേ കുടുംബത്തിലെ പഞ്ചസാര കുറയ്ക്കുന്ന മരുന്ന്", "hi": "एक ही वर्ग की शुगर कम करने वाली दवा"},
    "diuretic_k_sparing": {"en": "water tablet of the same family", "ml": "ഒരേ കുടുംബത്തിലെ മൂത്രവർദ്ധക മരുന്ന്", "hi": "एक ही वर्ग की पानी की गोली"},
    "fluoroquinolone": {"en": "antibiotic of the same family", "ml": "ഒരേ കുടുംബത്തിലെ ആന്റിബയോട്ടിക്", "hi": "एक ही वर्ग की एंटीबायोटिक"},
    "corticosteroid": {"en": "steroid of the same family", "ml": "ഒരേ കുടുംബത്തിലെ സ്റ്റിറോയിഡ്", "hi": "एक ही वर्ग का स्टेरॉयड"},
}

#: Risk phrases for interaction findings.
RISKS: dict[str, dict[str, str]] = {
    "bleeding": {
        "en": "the risk of serious bleeding goes up.",
        "ml": "ഗുരുതരമായ രക്തസ്രാവ സാധ്യത കൂടും.",
        "hi": "गंभीर खून बहने का खतरा बढ़ जाता है।",
    },
    "gi_bleed": {
        "en": "the stomach lining can ulcerate and bleed.",
        "ml": "വയറ്റിലെ ആവരണം വ്രണമായി രക്തസ്രാവം ഉണ്ടാകാം.",
        "hi": "पेट की परत में अल्सर होकर खून आ सकता है।",
    },
    "hyperkalemia": {
        "en": "potassium can rise to a dangerous level and disturb the heart rhythm.",
        "ml": "പൊട്ടാസ്യം അപകടകരമായി ഉയർന്ന് ഹൃദയമിടിപ്പ് താളം തെറ്റാം.",
        "hi": "पोटैशियम खतरनाक स्तर तक बढ़कर दिल की धड़कन बिगाड़ सकता है।",
    },
    "dual_blockade": {
        "en": "two blood pressure medicines of this type together can shut down kidney function.",
        "ml": "ഇത്തരത്തിലുള്ള രണ്ട് രക്തസമ്മർദ്ദ മരുന്നുകൾ ഒരുമിച്ച് വൃക്കയുടെ പ്രവർത്തനം തകരാം.",
        "hi": "इस तरह की दो ब्लड प्रेशर दवाएँ साथ में गुर्दे की काम करने की क्षमता घटा सकती हैं।",
    },
    "severe_hypotension": {
        "en": "blood pressure can fall so low that you faint.",
        "ml": "രക്തസമ്മർദ്ദം വളരെ കുറഞ്ഞ് ബോധക്ഷയം ഉണ്ടാകാം.",
        "hi": "ब्लड प्रेशर इतना गिर सकता है कि बेहोशी आ जाए।",
    },
    "hypotension": {
        "en": "blood pressure can drop and make you dizzy or faint.",
        "ml": "രക്തസമ്മർദ്ദം കുറഞ്ഞ് തലകറക്കമോ ബോധക്ഷയമോ ഉണ്ടാകാം.",
        "hi": "ब्लड प्रेशर गिरने से चक्कर या बेहोशी हो सकती है।",
    },
    "hypoglycemia": {
        "en": "blood sugar can fall very low, causing sweating, shaking and confusion.",
        "ml": "രക്തത്തിലെ പഞ്ചസാര വളരെ കുറഞ്ഞ് വിയർപ്പ്, വിറയൽ, ആശയക്കുഴപ്പം ഉണ്ടാകാം.",
        "hi": "ब्लड शुगर बहुत कम होकर पसीना, कंपन और भ्रम हो सकता है।",
    },
    "serotonin": {
        "en": "there is a risk of serotonin syndrome: agitation, fever, fast heartbeat.",
        "ml": "സെറടോണിൻ സിൻഡ്രോം സാധ്യത: അസ്വസ്ഥത, പനി, വേഗത്തിലുള്ള ഹൃദയമിടിപ്പ്.",
        "hi": "सिरोटोनिन सिंड्रोम का खतरा: बेचैनी, बुखार, तेज़ धड़कन।",
    },
    "reduced_efficacy": {
        "en": "this combination can make one of the medicines work less well.",
        "ml": "ഈ കൂടിച്ചേരൽ മരുന്നുകളിലൊന്നിന്റെ ഫലം കുറയ്ക്കാം.",
        "hi": "इस मेल से एक दवा का असर कम हो सकता है।",
    },
    "bradycardia": {
        "en": "the heart rate can become dangerously slow.",
        "ml": "ഹൃദയമിടിപ്പ് അപകടകരമായി മന്ദഗതിയിലാകാം.",
        "hi": "धड़कन खतरनाक रूप से धीमी हो सकती है।",
    },
}


#: A missing translation falls back to this language, never to a KeyError.
#: A new language can therefore be enabled with partial coverage and still
#: warn correctly in English while its strings land.
FALLBACK_LANGUAGE = "en"


def t(key: str, lang: Language | str, **kwargs: object) -> str:
    """Fetch a localised string, filling ``{placeholders}``.

    Unknown language codes and untranslated keys fall back to English rather
    than raising: a partial Tamil rollout must still produce a safe warning.
    """
    lang_code = lang.value if isinstance(lang, Language) else str(lang)
    bundle = TEXTS[key]
    template = bundle.get(lang_code) or bundle[FALLBACK_LANGUAGE]
    return template.format(**kwargs) if kwargs else template


def missing_keys(lang_code: str) -> list[str]:
    """Keys with no string for this language (used by the coverage test)."""
    return sorted(key for key, bundle in TEXTS.items() if not bundle.get(lang_code))


def coverage(lang_code: str) -> dict[str, object]:
    """Translation coverage for one language code."""
    missing = missing_keys(lang_code)
    total = len(TEXTS)
    return {
        "language": lang_code,
        "keys": total,
        "translated": total - len(missing),
        "percent": round(100 * (total - len(missing)) / total, 1) if total else 0.0,
        "missing": missing,
    }


def language_text(key: str, **kwargs: object) -> LanguageText:
    """Build the tri-lingual bundle the API returns for one field."""
    return LanguageText(
        en=t(key, Language.english, **kwargs),
        ml=t(key, Language.malayalam, **kwargs),
        hi=t(key, Language.hindi, **kwargs),
    )


def risk_text(risk: str) -> dict[str, str]:
    return RISKS[risk]


def class_group(drug_class: str) -> dict[str, str]:
    return CLASS_GROUP.get(
        drug_class,
        {"en": "the same group", "ml": "ഒരേ വിഭാഗം", "hi": "एक ही वर्ग"},
    )
