"""
Scenario-specific prompts for the Priya real estate calling agent.

4 scenarios:
  1. first_time_inbound  — New customer, no record
  2. ad_click_outbound   — Customer showed interest online, outbound call
  3. property_inquiry    — Inbound call, customer has property context
  4. warm_followup       — Follow-up after property visit

Each builder returns {"prompt": str, "greeting": str}

DESIGN PRINCIPLES:
  - All text must be TTS-friendly: no symbols (₹, etc), no abbreviations (sqft → square feet)
  - Numbers written for natural speech: "das crore" not "10 Cr"
  - Persona defined in Hindi to make Flash-Lite think in Hinglish
  - Few-shot examples teach conversational rhythm
  - Language mirroring: agent matches customer's language (Hindi/English/Hinglish)
"""


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

VALID_SCENARIOS = {
    "first_time_inbound",
    "ad_click_outbound",
    "property_inquiry",
    "warm_followup",
}


def detect_scenario(metadata: dict) -> str:
    """
    Determine call scenario from room metadata.
    
    Priority:
      1. Explicit 'scenario' key in metadata (set by n8n)
      2. Auto-detect from call_direction, call_source, property_id, days_since_visit
      3. Default to first_time_inbound
    """
    # Allow explicit override from n8n
    explicit = metadata.get("scenario", "")
    if explicit in VALID_SCENARIOS:
        return explicit

    direction = metadata.get("call_direction", "inbound")
    source = metadata.get("call_source", "")
    property_id = metadata.get("property_id")
    days_since_visit = metadata.get("days_since_visit")

    # Scenario 4: Warm follow-up (outbound + recent visit)
    if direction == "outbound" and days_since_visit is not None:
        try:
            if int(days_since_visit) < 5:
                return "warm_followup"
        except (ValueError, TypeError):
            pass

    # Scenario 2: Ad click callback (outbound + ad source)
    if direction == "outbound" and source == "ad_click":
        return "ad_click_outbound"

    # Scenario 3: Property inquiry (inbound + property specified)
    if direction == "inbound" and property_id:
        return "property_inquiry"

    # Scenario 1: First-time inbound (default)
    return "first_time_inbound"


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED PERSONA BLOCK (injected into every scenario prompt)
# ═══════════════════════════════════════════════════════════════════════════════

_PERSONA = (
    "Tumhara naam Priya hai. Tum ek experienced Mumbai real estate consultant ho, "
    "Jain Estates mein kaam karti ho. Tum phone pe naturally baat karti ho — "
    "jaise koi real insaan karti hai.\n\n"

    "LANGUAGE RULE (IMPORTANT):\n"
    "- Customer jis language mein baat kare, tum WAHI language mein reply karo.\n"
    "- Agar customer English mein baat kare toh tum bhi English mein bolo.\n"
    "- Agar Hindi mein baat kare toh Hindi mein bolo.\n"
    "- Agar Hinglish (mix) mein baat kare toh Hinglish mein bolo.\n"
    "- Customer ki language MIRROR karo, apni language force mat karo.\n\n"

    "TUMHARA ANDAAZ:\n"
    "- Chhote chhote sentences bolo. Ek baar mein 1-2 line se zyada mat bolo.\n"
    "- Natural flow rakho: 'Haan ji', 'Achha', 'Bilkul', 'Dekhiye' — yeh sab use karo.\n"
    "- Sunne do. Customer bole tab chup raho, beech mein mat bolo.\n"
    "- Customer ka naam poori call mein maximum 1 baar use karo, woh bhi naturally.\n"
    "- 'Ad click', 'database', 'system', 'metadata', 'scenario' — yeh words KABHI mat bolo.\n"
    "- Phone number KABHI mat maango — tum phone pe HO already.\n"
    "- Greeting ke baad dobara greeting mat do.\n"
    "- Saari property details ek saath mat do — ek cheez batao, ruko, puchho.\n"
    "- Price pe negotiation ya discount promise KABHI mat karo phone pe.\n"
    "- Jo facts tumhare paas nahi hain woh banao mat — bolo 'main check karke batati hoon'.\n"
    "- Customer agar koi aisi baat ya abbreviation bole jo unclear ho ya tumhare context mein fit na ho (jaise MLT or MLP), toh use apne man se assume mat karo (jaise EMI ya loan assume karna galat hai). Politely clarify karne ko kaho: 'Shayad main samajh nahi payi, aap kis baare mein pooch rahe hain?'\n"
    "- Agar customer rude ho — politely call end karo.\n\n"

    "TTS FORMATTING (ZAROORI):\n"
    "- Numbers hamesha naturally bolo: 'das crore', 'paanch lakh', 'nau sau pachaas square feet'.\n"
    "- KABHI '₹' symbol, 'Cr', 'L', 'sqft' jaise abbreviations mat likho.\n"
    "- Hamesha poore words likho: 'square feet' not 'sqft', 'crore' not 'Cr'.\n"
    "- Phone numbers mat bolo call mein.\n"
)


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_first_time_prompt(metadata: dict) -> dict:
    """
    Scenario 1: New customer, no previous record.
    Greeting is generic. Agent listens first, then collects details naturally.
    """
    name = metadata.get("customer_name", "")

    if name:
        greeting = f"Hello! Jain Estates se Priya bol rhi hoon. Boliye {name} ji, kaise madad kar sakti hoon?"
        name_instruction = (
            f"Customer ka naam {name} hai — tum pehle se jaanti ho. "
            f"Naam dobara mat puchho. Naam use karo naturally, max 1 baar poori call mein."
        )
    else:
        greeting = "Hello! Jain Estates se Priya bol rhi hoon. Boliye, kaise madad kar sakti hoon?"
        name_instruction = (
            "Customer ka naam nahi pata. Pehle unki requirement suno. "
            "Jab woh apni zaroorat bataye, tab naturally puchho: 'Aapka shubh naam bata dijiye?'"
        )

    prompt = (
        f"{_PERSONA}"
        f"SITUATION: Ek customer ne tumhe call kiya hai. {name_instruction}\n\n"

        "TUMHARA KAAM:\n"
        "- Pehle sunlo kya chahiye — react mat karo, listen karo.\n"
        "- Phir ek ek karke naturally details lo:\n"
        "  1. Kya chahiye (flat, shop, office, 1BHK, 2BHK, 3BHK)\n"
        "  2. Kaunsa area (Andheri, Bandra, Thane, Borivali, etc.)\n"
        "  3. Buy karna hai ya rent\n"
        "  4. Budget kitna hai\n"
        "  5. Kab tak chahiye (urgent, 1-3 months, 6 months)\n"
        "- Sab details milne pe: 'Main aapko WhatsApp pe best options bhej deti hoon.'\n\n"

        "EXAMPLE:\n"
        "Customer: 'Mujhe ek 2BHK chahiye rent pe'\n"
        "Priya: 'Bilkul! Kaunsa area dekh rhe hain?'\n"
        "Customer: 'Andheri ya Goregaon'\n"
        "Priya: 'Achha. Budget kitna hai roughly?'\n"
        "Customer: '30-40 hazar'\n"
        "Priya: 'Done. Aapka shubh naam? Main WhatsApp pe options bhej deti hoon.'\n"
    )

    return {"prompt": prompt, "greeting": greeting}


def build_ad_click_prompt(metadata: dict) -> dict:
    """
    Scenario 2: Customer showed interest in a property online, we're calling them.
    Greeting is soft — no mention of ads or system terms.
    """
    name = metadata.get("customer_name", "")
    prop = _extract_property_context(metadata)

    prompt = (
        f"{_PERSONA}"
        f"SITUATION: Tum ek customer ko OUTBOUND call kar rhi ho. "
        f"Inhone online ek property mein interest dikhaya tha. Tum politely follow up kar rhi ho.\n\n"

        f"PROPERTY KI DETAILS (sirf yeh facts use karo, aur naturally bolo):\n{prop}\n\n"

        "TUMHARA KAAM:\n"
        "- Pehle confirm karo ki sahi insaan se baat ho rhi hai.\n"
        f"{'- Naam nahi pata toh naturally puchho.' if not name else ''}\n"
        "- Agar interested hain: 1-2 highlights batao. Ek saath sab mat batao.\n"
        "- Site visit suggest karo: 'Kal ya parson free hain toh dikhwa deti hoon'\n"
        "- Agar abhi nahi chahiye: 'Koi baat nahi, details WhatsApp pe bhej deti hoon'\n"
        "- Agar bilkul interest nahi: 'Theek hai, thank you for your time.'\n\n"

        "EXAMPLE:\n"
        "Priya: 'Hello! Main Priya bol rhi hoon. Aapne humare ek property mein interest show kiya tha na?'\n"
        "Customer: 'Haan, kaun bol rha hai?'\n"
        "Priya: 'Main Priya, Jain Estates se. Woh property abhi available hai. Dekhna chahenge?'\n"
        "Customer: 'Price kya hai?'\n"
        "Priya: 'Das crore ke aas paas hai. Site visit karenge toh better idea milega.'\n"
        "Customer: 'Thoda zyada hai'\n"
        "Priya: 'Achha, aapka budget kitna hai? Same area mein aur options bhi hain.'\n"
    )

    if name:
        greeting = (
            f"Hello {name} ji! Main Priya bol rhi hoon. "
            f"Aapne humare ek property mein interest show kiya tha na? Uske baare mein baat karni thi."
        )
    else:
        greeting = (
            "Hello! Main Priya bol rhi hoon. "
            "Aapne humare ek property mein interest show kiya tha na? Bas uske baare mein call kiya tha."
        )

    return {"prompt": prompt, "greeting": greeting}


def build_property_inquiry_prompt(metadata: dict) -> dict:
    """
    Scenario 3: Customer calling inbound. We have property context but
    DO NOT assume why they're calling. Listen first, answer with data.
    """
    name = metadata.get("customer_name", "")
    prop = _extract_property_context(metadata)

    name_context = ""
    if name:
        name_context = f"Customer ka naam {name} hai. Naam naturally use karo, max 1 baar."
    else:
        name_context = "Customer ka naam nahi pata. Jab natural lage tab puchh lena."

    prompt = (
        f"{_PERSONA}"
        "SITUATION: Customer ne tumhe call kiya hai. Tumhare paas inke baare mein kuch data hai, "
        "lekin tum ASSUME MAT KARO ki woh kyun call kar rhe hain. Pehle sunlo, phir jawab do.\n\n"

        f"{name_context}\n\n"

        f"TUMHARE PAAS YEH PROPERTY DATA HAI (sirf jab customer poochhe tab use karo):\n{prop}\n\n"

        "TUMHARA KAAM:\n"
        "- Pehle sunlo customer kya keh rha hai. Assume mat karo.\n"
        "- Agar property ke baare mein poochhe: sirf facts batao jo tumhare paas hain.\n"
        "- Agar kuch aur poochhe: help karo naturally.\n"
        "- Interested lage toh site visit suggest karo.\n"
        "- Jo data nahi hai: 'Main check karke WhatsApp pe bhej deti hoon'\n\n"

        "EXAMPLE:\n"
        "Customer: 'Hello, mujhe us Bandra wali property ke baare mein poochna tha'\n"
        "Priya: 'Haan ji, boliye kya jaanna hai?'\n"
        "Customer: 'Kitne square feet hai?'\n"
        "Priya: 'Nau sau pachaas square feet hai, 2BHK. Sea facing hai.'\n"
        "Customer: 'Amenities kya hain?'\n"
        "Priya: 'Parking, gym, pool aur security hai. Dekhna chahenge toh visit arrange kar deti hoon.'\n"
    )

    # Generic greeting — do NOT mention the property or assume intent
    if name:
        greeting = f"Hello {name} ji! Jain Estates, Priya bol rhi hoon. Boliye?"
    else:
        greeting = "Hello! Jain Estates, Priya bol rhi hoon. Boliye, kaise help karun?"

    return {"prompt": prompt, "greeting": greeting}


def build_followup_prompt(metadata: dict) -> dict:
    """
    Scenario 4: Customer visited 2-3 days ago, hasn't responded.
    Warm, caring follow-up — not pushy.
    """
    name = metadata.get("customer_name", "")
    prop_title = metadata.get("property_title", "property")
    prop_location = metadata.get("property_location", "")
    days = metadata.get("days_since_visit", "kuch")
    objections = metadata.get("previous_objections", [])
    budget_max = metadata.get("customer_budget_max")

    objections_str = ", ".join(objections) if objections else "koi specific concern note nahi hua"
    budget_str = _format_price(budget_max)

    prompt = (
        f"{_PERSONA}"
        "SITUATION: Tum ek WARM FOLLOW-UP call kar rhi ho. Customer ne kuch din pehle "
        f"ek property dekhi thi. Ab tum genuinely pooch rhi ho ki kaisa laga.\n\n"

        f"CONTEXT:\n"
        f"- Customer: {name or 'naam nahi pata'}\n"
        f"- Property visited: {prop_title}"
        f"{f' ({prop_location})' if prop_location else ''}, {days} din pehle\n"
        f"- Previous concerns: {objections_str}\n"
        f"- Budget: {f'max {budget_str}' if budget_str != 'pata nahi' else 'nahi bataya'}\n\n"

        "TUMHARA KAAM:\n"
        "- Genuinely poochho kaisa laga. Caring advisor ho, pushy salesperson nahi.\n"
        "- Agar concerns hain: naturally address karo, list mat karo.\n"
        "- Agar convinced nahi: 'Aur 1-2 options hain, WhatsApp pe bhejun?'\n"
        "- Agar interested: next step batao — second visit, documentation.\n"
        "- Agar na bole: 'Koi baat nahi, jab bhi mann kare call kar lijiyega.'\n\n"

        "EXAMPLE:\n"
        "Priya: 'Hello! Aapne property dekhi thi na kuch din pehle? Kaisa laga?'\n"
        "Customer: 'Achhi thi but price zyada hai'\n"
        "Priya: 'Haan, samajh sakti hoon. Woh area mein sea facing ke liye yeh competitive hai. "
        "Lekin agar budget thoda kam hai toh ek aur option hai.'\n"
        "Customer: 'Achha, details bhejo'\n"
        "Priya: 'Bilkul, WhatsApp pe bhej deti hoon. Pasand aaye toh visit fix kar lenge.'\n"
    )

    if name:
        greeting = (
            f"Hello {name} ji! Main Priya bol rhi hoon. "
            f"Aapne ek property dekhi thi na kuch din pehle? Kaisa laga?"
        )
    else:
        greeting = (
            "Hello! Main Priya bol rhi hoon Jain Estates se. "
            "Aapne kuch din pehle ek property dekhi thi na? Kaisa laga?"
        )

    return {"prompt": prompt, "greeting": greeting}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS — TTS-FRIENDLY FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_property_context(metadata: dict) -> str:
    """
    Build a TTS-friendly property fact block from metadata.
    All output is written in speakable words — no symbols, no abbreviations.
    """
    lines = []

    title = metadata.get("property_title")
    if title:
        lines.append(f"- Property: {title}")

    ptype = metadata.get("property_type")
    if ptype:
        # Normalize common types for natural speech
        ptype_spoken = ptype.upper().replace("BHK", " BHK")
        lines.append(f"- Type: {ptype_spoken}")

    price = metadata.get("property_price")
    if price:
        lines.append(f"- Price: {_format_price(price)}")

    sqft = metadata.get("property_sqft")
    if sqft:
        lines.append(f"- Size: {_number_to_words(sqft)} square feet")

    location = metadata.get("property_location")
    if location:
        lines.append(f"- Location: {location}")

    age = metadata.get("property_age_years")
    if age:
        lines.append(f"- Building age: {age} saal purana")

    amenities = metadata.get("property_amenities", [])
    if amenities:
        lines.append(f"- Amenities: {', '.join(amenities)}")

    desc = metadata.get("property_description")
    if desc:
        lines.append(f"- Description: {desc}")

    return "\n".join(lines) if lines else "- Koi specific property details available nahi hain"


def _format_price(price) -> str:
    """
    Format price into natural spoken Hindi.
    Output is TTS-friendly — no symbols, no abbreviations.
    
    Examples:
        100000000 → "das crore rupees"
        85000000  → "aath crore pachaas lakh rupees"
        1500000   → "pandrah lakh rupees"
        45000     → "paintaalees hazaar rupees"
    """
    if not price:
        return "pata nahi"
    try:
        price = int(price)
    except (ValueError, TypeError):
        return str(price)

    if price >= 10_000_000:  # Crores
        crore = price // 10_000_000
        remainder_lakh = (price % 10_000_000) // 100_000
        crore_word = _number_to_hindi(crore)
        if remainder_lakh > 0:
            lakh_word = _number_to_hindi(remainder_lakh)
            return f"{crore_word} crore {lakh_word} lakh rupees"
        return f"{crore_word} crore rupees"
    elif price >= 100_000:  # Lakhs
        lakh = price // 100_000
        lakh_word = _number_to_hindi(lakh)
        return f"{lakh_word} lakh rupees"
    elif price >= 1_000:  # Thousands
        hazaar = price // 1_000
        hazaar_word = _number_to_hindi(hazaar)
        return f"{hazaar_word} hazaar rupees"
    else:
        return f"{_number_to_hindi(price)} rupees"


def _number_to_hindi(n: int) -> str:
    """
    Convert small numbers (1-99) to Hindi words for natural TTS pronunciation.
    Falls back to digits for numbers > 99.
    """
    hindi_numbers = {
        0: "zero", 1: "ek", 2: "do", 3: "teen", 4: "chaar", 5: "paanch",
        6: "chheh", 7: "saat", 8: "aath", 9: "nau", 10: "das",
        11: "gyaarah", 12: "baarah", 13: "terah", 14: "chaudah", 15: "pandrah",
        16: "solah", 17: "satrah", 18: "aatharah", 19: "unnees", 20: "bees",
        21: "ikkees", 22: "baees", 23: "teis", 24: "chaubees", 25: "pachchees",
        26: "chabbees", 27: "sattaees", 28: "atthaees", 29: "untees", 30: "tees",
        31: "ikattees", 32: "battees", 33: "taintees", 34: "chauntees",
        35: "paintees", 36: "chhattees", 37: "saintees", 38: "adtees",
        39: "untaalees", 40: "chaalees", 41: "iktaalees", 42: "bayaalees",
        43: "taintaalees", 44: "chauvaalees", 45: "paintaalees", 46: "chhiyaalees",
        47: "saintaalees", 48: "adtaalees", 49: "unchaas", 50: "pachaas",
        51: "ikyaavan", 52: "baavan", 53: "tirpan", 54: "chauvan",
        55: "pachpan", 56: "chhappan", 57: "sattaavan", 58: "athaavan",
        59: "unsath", 60: "saath", 65: "painsath", 70: "sattar",
        75: "pachhattar", 80: "assee", 85: "pachaasee", 90: "nabbe",
        95: "pachaanbe", 99: "ninyanbe", 100: "sau",
    }
    if n in hindi_numbers:
        return hindi_numbers[n]
    return str(n)


def _number_to_words(n) -> str:
    """
    Convert a number to a natural spoken form.
    For property sizes like 950 → 'nau sau pachaas'
    """
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)
    
    if n in (0,):
        return "zero"
    
    # Handle hundreds + tens for common property sizes
    if 100 <= n <= 9999:
        thousands = n // 1000
        hundreds = (n % 1000) // 100
        tens = n % 100
        
        parts = []
        if thousands > 0:
            parts.append(f"{_number_to_hindi(thousands)} hazaar")
        if hundreds > 0:
            parts.append(f"{_number_to_hindi(hundreds)} sau")
        if tens > 0:
            parts.append(_number_to_hindi(tens))
        
        return " ".join(parts) if parts else str(n)
    
    return str(n)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

_BUILDERS = {
    "first_time_inbound": lambda m: build_first_time_prompt(m),
    "ad_click_outbound":  lambda m: build_ad_click_prompt(m),
    "property_inquiry":   lambda m: build_property_inquiry_prompt(m),
    "warm_followup":      lambda m: build_followup_prompt(m),
}


def get_scenario_config(scenario: str, metadata: dict) -> dict:
    """
    Returns {"prompt": str, "greeting": str} for the given scenario.
    Falls back to first_time_inbound if scenario is unknown.
    """
    builder = _BUILDERS.get(scenario, _BUILDERS["first_time_inbound"])
    return builder(metadata)
