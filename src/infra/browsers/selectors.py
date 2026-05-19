"""
Shared selectors for browser agents to avoid duplication.
"""

# Google Search
GOOGLE_COOKIE_ACCEPT_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accepter tout')",
    "#L2AGLb",
    "button#L2AGLb",
    "button#W0wltc"
]

GOOGLE_AI_MODE_TAB_SELECTORS = [
    "a:has-text('Mode IA')",
    "a:has-text('IA')",
    "a:has-text('AI Mode')",
    "a:has-text('AI')"
]

GOOGLE_AI_RESPONSE_SELECTORS = [
    "code",
    ".kp-wholepage-osrp-ent",
    "div.mod",
    ".xpdopen .c2xzTb",
    "[data-attrid='wa:/description']",
    "div[jsname='yEVEwb']"
]

# Generic Input
GENERIC_CHAT_INPUT_SELECTORS = [
    "div[role='combobox']",
    ".ql-editor",
    "textarea"
]
