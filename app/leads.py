import re

# Bangla digits -> English digits, e.g. ০৭৭০০ -> 07700
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")

NAME_PATTERNS = [
    # English: "my name is Rahim"
    re.compile(r"(?:my name is|my name's|name is|this is)\s+"
               r"([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.I),
    # Banglish: "amar nam rahim", "amr nam rahim"
    re.compile(r"(?:amar|amr)\s+(?:nam|name)\s+"
               r"([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.I),
    # Bangla: "আমার নাম রহিম"
    re.compile(r"আমার\s+নাম\s+([\u0980-\u09FF]+(?:\s+[\u0980-\u09FF]+){0,2})"),
]
# words that can follow a name but are not part of it
NAME_STOP = {"holo", "hocche", "hoche", "hoy", "ki", "is", "kintu", "ami",
             "হলো", "হচ্ছে", "কি", "কিন্তু", "আমি"}

# short replies that mean "no"
NO_WORDS = {"na", "naa", "no", "nope", "nah", "না", "dibo na", "debo na",
            "dite chai na", "chai na", "lagbe na", "দিব না", "দেব না", "চাই না"}


def empty_lead():
    return {"name": None, "phone": None, "email": None, "declined": []}


def find_email(text):
    match = EMAIL_RE.search(text)
    return match.group(0).lower() if match else None


def find_phone(text):
    """Return a phone number with 9-15 digits, or None."""
    for match in PHONE_RE.finditer(text.translate(BANGLA_DIGITS)):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if 9 <= len(digits) <= 15:
            return ("+" if raw.startswith("+") else "") + digits
    return None


def find_name(text):
    for pattern in NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            words = []
            for word in match.group(1).split():
                if word.lower() in NAME_STOP:
                    break
                words.append(word)
            if words:
                name = " ".join(words)
                return name.title() if name.isascii() else name
    return None


# words that name each detail (after normalising: lower case, no hyphens)
DETAIL_WORDS = {
    "email": ["ইমেইল", "মেইল", "email", "mail", "imail", "imeil"],
    "phone": ["ফোন", "মোবাইল", "phone", "mobile", "number", "nombor", "nambar", "নম্বর", "নাম্বার"],
    "name": ["নাম", "name", "nam"],
}
# when reading the BOT's question, "number/নম্বর" is too loose (it appears next to
# Beneco's own office number), so only these words count as "asking for the phone"
BOT_PHONE_WORDS = ["ফোন", "মোবাইল", "phone", "mobile"]

# phrases that mean "I won't give / don't want"
NEGATIONS = ["dibo na", "debo na", "dibona", "debona", "dite chai na", "chai na",
             "lagbe na", "bolbo na", "bolte chai na", "share korbo na",
             "দিব না", "দিবো না", "দেব না", "দেবো না", "দিতে চাই না", "চাই না",
             "লাগবে না", "বলব না", "বলবো না", "শেয়ার করব না",
             "don't want", "dont want", "won't", "wont", "no thanks", "not share"]

_DASHES = dict.fromkeys(map(ord, "-\u2010\u2011\u2012\u2013\u2014\u00ad\u200c\u200d"), None)


def _normalise(text):
    """Lower case and remove hyphens/invisible joiners, so ই‑মেইল == ইমেইল."""
    return (text or "").lower().translate(_DASHES)


def _last_question(bot_message):
    """The part of the bot's message that contains its last question."""
    text = _normalise(bot_message)
    if "?" in text:
        text = text[: text.rindex("?")]
        for mark in ("?", "।", "."):
            if mark in text:
                text = text[text.rindex(mark) + 1:]
    return text


def find_refusal(text, last_bot_message):
    """Return which detail the customer refused ("email", "phone", "name") or None."""
    msg = _normalise(text).strip().strip("।.!?")

    # 1. a refusal that names the detail, at any length: "email dibo na", "ইমেইল দেব না"
    best_field, best_pos = None, -1
    for neg in NEGATIONS:
        neg_pos = msg.find(neg)
        if neg_pos == -1:
            continue
        for field, words in DETAIL_WORDS.items():
            for word in words:
                word_pos = msg.rfind(word, 0, neg_pos)   # detail word just before "dibo na"
                if word_pos > best_pos:
                    best_field, best_pos = field, word_pos
    if best_field:
        return best_field

    # 2. a short "no" that answers the bot's last question: "na", "no", "না"
    if len(msg.split()) > 4 or msg not in NO_WORDS:
        return None
    asked = _last_question(last_bot_message)
    if any(w in asked for w in DETAIL_WORDS["email"]):
        return "email"
    if any(w in asked for w in BOT_PHONE_WORDS):
        return "phone"
    if any(w in asked for w in DETAIL_WORDS["name"]):
        return "name"
    return None


def update_lead(lead, message, history):
    """Update the customer record from a new message.
    Returns (lead, is_new_contact). is_new_contact is True when a new phone or email arrived."""
    lead = {**empty_lead(), **(lead or {})}
    lead["declined"] = list(lead.get("declined") or [])
    is_new_contact = False

    name = find_name(message)
    if name and name != lead["name"]:
        lead["name"] = name

    phone = find_phone(message)
    if phone and phone != lead["phone"]:
        lead["phone"] = phone
        is_new_contact = True

    email = find_email(message)
    if email and email != lead["email"]:
        lead["email"] = email
        is_new_contact = True

    # a detail that was given is no longer "declined"
    lead["declined"] = [d for d in lead["declined"] if not lead.get(d)]

    last_bot = next((m["content"] for m in reversed(history or [])
                     if m.get("role") == "assistant"), "")
    refused = find_refusal(message, last_bot)
    if refused and not lead.get(refused) and refused not in lead["declined"]:
        lead["declined"].append(refused)

    return lead, is_new_contact


def lead_summary(lead):
    """The note shown to the bot with every message."""
    lead = lead or empty_lead()
    declined = lead.get("declined") or []

    def show(field, label):
        if lead.get(field):
            if field == "phone":
                return f"- {label}: {lead[field]} (already given; do not ask again and do not repeat it)"
            return f"- {label}: {lead[field]} (already given, never ask again)"
        if field in declined:
            return f"- {label}: customer said no (never ask again)"
        return f"- {label}: not given yet"

    return "\n".join([
        "CUSTOMER DETAILS (from this conversation):",
        show("name", "Name"),
        show("phone", "Phone"),
        show("email", "Email"),
    ])