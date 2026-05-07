import re

with open("src/infra/browsers/camoufox_agent.py", "r") as f:
    code = f.read()

# Fix search_gemini_ai
code = re.sub(
    r"if not self\._page:\s+return None\s+try:",
    r"page = self._page\n        if not page:\n            return None\n        try:",
    code
)

code = re.sub(
    r"self\._page\.",
    r"page.",
    code
)

# wait, replacing all `self._page.` might break `__init__` and `start` and `close`.
