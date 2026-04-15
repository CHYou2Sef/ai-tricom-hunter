#!/usr/bin/env python3
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  GitAgent Definition Validator                                    ║
# ║  Native Python replacement for GitAgent CLI to ensure zero NPM    ║
# ║  dependencies while validating agent config on CI/CD & Deploy.    ║
# ╚═══════════════════════════════════════════════════════════════════╝

import os
import yaml
import sys

def validate_agent():
    print("🔍 Validating Native Agent Architecture...")
    required_files = ["agent.yaml", "SOUL.md", "RULES.md"]
    missing = [f for f in required_files if not os.path.exists(f)]
    
    if missing:
        print(f"❌ Validation Failed: Missing required files: {missing}")
        sys.exit(1)

    print("✅ Found all core definition files (agent.yaml, SOUL.md, RULES.md).")

    try:
        with open("agent.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            if "name" not in config or "model" not in config:
                print("❌ Validation Failed: agent.yaml is missing 'name' or 'model' keys.")
                sys.exit(1)
            print("✅ agent.yaml YAML syntax is valid and core attributes exist.")
    except Exception as e:
        print(f"❌ Validation Failed: Could not parse agent.yaml. Error: {e}")
        sys.exit(1)

    print("🎉 Agent Definition is COMPLIANT!")

if __name__ == "__main__":
    validate_agent()
