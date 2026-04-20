import os
import re

REPLACEMENTS = [
    # Top-level to Package
    (r"import config\b", "from core import config"),
    (r"from utils\.logger import", "from core.logger import"),
    (r"from utils\.singleton import", "from core.singleton import"),
    (r"from utils\.observability import", "from core.observability import"),
    (r"from utils\.fs import", "from common.fs import"),
    (r"from utils\.health_check import", "from common.health_check import"),
    
    # Internal domains
    (r"from browser\.", "from infra.browsers."),
    (r"from llm\.", "from infra.intelligence."),
    (r"from excel\.", "from domain.excel."),
    (r"from search\.", "from domain.search."),
    (r"from enrichment\.", "from domain.enrichment."),
    (r"from utils\.", "from common."),
    (r"from agent\b", "from app.orchestrator"),
    (r"from api\b", "from app.monitoring"),
]

def fix_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for pattern, replacement in REPLACEMENTS:
        new_content = re.sub(pattern, replacement, new_content)
    
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed: {path}")

def run():
    for folder in ["src", "run", "tests"]:
        if not os.path.exists(folder): continue
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.endswith(".py"):
                    fix_file(os.path.join(root, file))

if __name__ == "__main__":
    run()
