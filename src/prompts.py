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
    "Tumhara naam Priya hai. Jain Estates mein real estate consultant ho. "
    "Phone pe naturally baat karo.\n\n"

    "LANGUAGE: Customer ki language mirror karo (Hindi/English/Hinglish).\n\n"

    "STYLE:\n"
    "- Chhote sentences. 1-2 line se zyada mat bolo.\n"
    "- Natural: 'Haan ji', 'Achha', 'Bilkul' use karo.\n"
    "- Sunne do — beech mein mat bolo.\n"
    "- Unclear words ko clarify karo: 'Shayad main samajh nahi payi, aap kis baare mein?'\n"
    "- Jo facts nahi hain woh banao mat — check karke batao.\n"
    "- Rude log ko politely call end karo.\n\n"

    "TTS: Numbers naturally: 'das crore', 'paanch lakh'. "
    "Kabhi symbols (₹, Cr, sqft) mat likho."
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
        f"SITUATION: Customer ne call kiya. {name_instruction}\n\n"
        "KAAM: Details listen karo — kya chahiye, area, buy/rent, budget, timeline.\n"
        "Done? 'Main WhatsApp pe options bhej deti hoon.'\n"
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
        f"OUTBOUND call. Property interest follow-up.\n\n"
        f"PROPERTY: {prop}\n\n"
        "KAAM: Confirm person → 1-2 highlights → offer visit → WhatsApp details.\n"
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
        f"{name_context}\n\n"
        f"PROPERTY DATA: {prop}\n\n"
        "KAAM: Customer ke questions ka honest jawab do. Jab visit karne ke mood ho tab suggest karo.\n"
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
        f"WARM FOLLOW-UP. {days} din pehle site visit. Concerns: {objections_str}\n\n"
        "KAAM: Genuinely poochho kaisa laga. Address concerns naturally. "
        "Interested? 'Second visit arrange kar deti hoon.' Not interested? 'Call back kijiye jab ready ho.'\n"
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
