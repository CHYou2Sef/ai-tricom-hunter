import subprocess
import sys
from pathlib import Path

def run_sast():
    """ Runs Bandit static analysis on the codebase. """
    print("🔍 [SAST] Starting Bandit scan...")
    
    root_dir = Path(__file__).parent.parent
    
    try:
        # Run bandit: -r (recursive), -ll (medium/high level), -x (exclude tests)
        result = subprocess.run(
            ["bandit", "-r", ".", "-ll", "-x", "./tests,./venv", "-f", "txt"],
            cwd=root_dir,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ [SAST] No critical security issues found.")
        else:
            print("⚠️ [SAST] Bandit found potential issues:")
            print(result.stdout)
            
    except FileNotFoundError:
        print("❌ [SAST] Error: 'bandit' not found. Please install it with 'pip install bandit'.")
        sys.exit(1)

if __name__ == "__main__":
    run_sast()
