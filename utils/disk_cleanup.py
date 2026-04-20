import os
import shutil
import glob
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

def check_and_cleanup(threshold_pct: int = 80):
    """
    Checks disk usage on /tmp and performs deep cleanup if it exceeds threshold.
    Also cleans up known zombie browser directories.
    """
    tmp_path = "/tmp"
    
    # 1. Check Disk Usage
    try:
        usage = shutil.disk_usage(tmp_path)
        percent_used = (usage.used / usage.total) * 100
        
        if percent_used > threshold_pct:
            logger.warning(f"⚠️  Disk space critical in /tmp ({percent_used:.1f}% used). Performing Deep Recovery...")
            _deep_purge()
        else:
            # Always do a light purge of known zombie folders
            _light_purge()
    except Exception as e:
        logger.debug(f"Disk check failed: {e}")

def _light_purge():
    """Wipes known temporary browser directories that are often left behind."""
    patterns = [
        "/tmp/uc_*",           # undetected-chromedriver profiles
        "/tmp/puppeteer_*",     # playwright/patchright artifacts
        "/tmp/.org.chromium.*", # chromium lock files
        "/tmp/antigravity-nsjail-sandbox-*", # sandbox artifacts
    ]
    
    cleaned_count = 0
    for pattern in patterns:
        for folder in glob.glob(pattern):
            try:
                if os.path.isdir(folder):
                    shutil.rmtree(folder, ignore_errors=True)
                else:
                    os.remove(folder)
                cleaned_count += 1
            except:
                pass
    
    if cleaned_count > 0:
        logger.info(f"🧹 Cleaned up {cleaned_count} zombie temporary directories.")

def _deep_purge():
    """More aggressive cleanup for emergency space recovery."""
    _light_purge()
    # Handle older log files or core dumps if necessary
    for core_file in glob.glob("/tmp/core.*"):
        try:
            os.remove(core_file)
        except:
            pass

if __name__ == "__main__":
    # Manual trigger
    check_and_cleanup(threshold_pct=0) # Force cleanup
