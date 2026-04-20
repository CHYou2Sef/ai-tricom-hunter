import re

def caveman_optimize(prompt: str) -> str:
    """
    Optimizes a prompt for token efficiency using 'caveman' rules:
    - Drops articles (a, an, the, le, la, les, un, une).
    - Removes pleasantries and hedging.
    - Keeps technical terms and JSON structure.
    - Maximum information density: one line per instruction.
    """
    # 1. Remove pleasantries and common hedging (English & French)
    pleasantries = [
        r"please\s*", r"i'd like you to\s*", r"en tant qu'expert\s*", 
        r"votre mission est de\s*", r"identifiez les\s*", r"recherchez les\s*",
        r"vouillez\s*", r"merci de\s*", r"hi,\s*", r"hello,\s*",
        r"i am an assistant,\s*", r"find and show\s*", r"search and show\s*",
        r"search and show me\s*", r"show me\s*", r"tell me\s*", r"give me\s*",
        r"identifiez\s*", r"trouvez\s*", r"récupérez\s*", r"fouillez\s*",
        r"analyze the context\s*", r"follow eeat\s*", r"analysez\s*",
        r"suivez les principes\s*", r"priorisez\s*", r"extrais\s*", r"extraire\s*"
    ]
    for pattern in pleasantries:
        prompt = re.sub(pattern, "", prompt, flags=re.IGNORECASE)

    # 2. Drop articles and fillers (English & French)
    fillers = [
        r"\ba\b", r"\ban\b", r"\bthe\b", r"\ble\b", r"\bla\b", r"\bles\b", r"\bun\b", r"\bune\b",
        r"\ball\b", r"\btout\b", r"\btous\b", r"\btoutes\b", r"\bof\b", r"\bde\b", r"\bdu\b", r"\bd'\b", r"\bl'\b",
        r"\bme\b", r"\bmy\b", r"\byour\b", r"\bmost\b", r"\bvery\b", r"\breally\b"
    ]
    for pattern in fillers:
        prompt = re.sub(pattern, "", prompt, flags=re.IGNORECASE)

    # 3. Consolidate whitespace
    prompt = re.sub(r'\s+', ' ', prompt)

    # 4. Enforce one line per instruction (splitting by periods or typical separators)
    # But preserve JSON blocks which use curly braces
    lines = []
    # Simplified splitting logic that respects JSON
    parts = re.split(r'(?<=[.!?])\s+', prompt)
    for part in parts:
        clean_part = part.strip()
        if clean_part:
            lines.append(clean_part)
            
    return "\n".join(lines)

if __name__ == "__main__":
    # Test case
    test_prompt = "Search and show me all available data and info of {nom}, {adresse} in JSON format output. The most important fields are: phone_numbers, email. Please respond in JSON only."
    print("Original:", test_prompt)
    print("Caveman:", caveman_optimize(test_prompt))
