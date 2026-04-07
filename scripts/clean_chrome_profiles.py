#!/usr/bin/env python3
"""
scripts/clean_chrome_profiles.py

A maintenance script to clean up Playwright Chrome profiles.
It removes heavy Cache folders (Service Worker Cache, Code Cache, DawnCache, etc.)
while keeping essential session cookies and extensions.

Run this weekly to prevent your hard drive from filling up.
"""

import os
import shutil
from pathlib import Path
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("ProfileCleaner")

def list_profiles(root_dir: str):
    """Find all worker profiles in the given root dir."""
    profiles = []
    if not os.path.exists(root_dir):
        return profiles
        
    for item in os.listdir(root_dir):
        if item.startswith("profile_worker_"):
            profiles.append(os.path.join(root_dir, item))
    return profiles

def clean_profile(profile_path: str):
    """Delete known heavy cache directories within a Chrome Profile."""
    logger.info(f"Cleaning profile: {os.path.basename(profile_path)}")
    
    # Target directories to wipe inside the profile
    cache_targets = [
        "Default/Cache",
        "Default/Code Cache",
        "Default/Service Worker/CacheStorage",
        "Default/Service Worker/ScriptCache",
        "Default/GPUCache",
        "GrShaderCache",
        "ShaderCache",
        "DawnCache",
        "Crashpad"
    ]
    
    bytes_freed = 0
    items_deleted = 0
    
    for target in cache_targets:
        full_target = os.path.join(profile_path, target)
        if os.path.exists(full_target):
            try:
                # Calculate size before deletion
                size = 0
                for path, dirs, files in os.walk(full_target):
                    for f in files:
                        fp = os.path.join(path, f)
                        if not os.path.islink(fp):
                            size += os.path.getsize(fp)
                
                shutil.rmtree(full_target)
                bytes_freed += size
                items_deleted += 1
                logger.debug(f"  - Deleted {target} (Freed {size / (1024*1024):.2f} MB)")
            except Exception as e:
                logger.warning(f"  - Failed to delete {target}: {e}")
                
    return bytes_freed, items_deleted

def main():
    logger.info("🧹 Starting Chrome Profile cleanup...")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    profiles = list_profiles(base_dir)
    if not profiles:
        logger.info("No worker profiles found. Nothing to clean.")
        return
        
    total_freed = 0
    for p in profiles:
        freed, deleted = clean_profile(p)
        total_freed += freed
        
    mb_freed = total_freed / (1024 * 1024)
    logger.info(f"✨ Cleanup complete! Freed {mb_freed:.2f} MB across {len(profiles)} profiles.")

if __name__ == "__main__":
    main()
