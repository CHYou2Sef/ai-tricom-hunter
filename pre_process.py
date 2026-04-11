"""
╔══════════════════════════════════════════════════════════════════════════╗
║            Phase 1: Pre-Processing & Classification                      ║
║                                                                          ║
║  This script watches the 'incoming' folder, cleans the raw files,        ║
║  splits them into categories, and moves the original to 'archived'.      ║
║                                                                          ║
║  Run this BEFORE the agent if you want to verify/edit your data.         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import time
import shutil
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import config
from excel.reader import read_excel
from excel.cleaner import clean_and_classify
from utils.logger import get_logger

logger = get_logger("PreProcessor")

class RawFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            self.handle_event(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.handle_event(event.dest_path)

    def handle_event(self, filepath):
        file_path = Path(filepath)
        
        # Immediate check
        if not file_path.exists():
            return

        ext = file_path.suffix.lower()
        if ext in config.ACCEPTED_EXTENSIONS:
            filename = file_path.name
            
            # Skip hidden/lock files
            if filename.startswith((".", "~")):
                return
                
            logger.info(f"[Phase 1] New file detected: {filename}")
            
            # Wait for file to settle
            time.sleep(config.FILE_SETTLE_DELAY)
            
            if not file_path.exists():
                logger.warning(f"  ⚠️ File vanished during settle delay: {filename}")
                return

            try:
                from utils.chunker import FileChunker
                # Use default chunk directory (WORK/CHUNKS) to avoid watching ourselves
                chunker = FileChunker()
                chunk_paths = chunker.split_file(filepath)

                for chunk_path in chunk_paths:
                    # Read the chunk (or original if small)
                    if not chunk_path.exists():
                        continue
                        
                    rows, mapping = read_excel(str(chunk_path))
                    if not rows:
                        logger.warning(f"  Empty file/chunk: {chunk_path.name}")
                        continue

                    original_headers = list(rows[0].raw.keys())
                    
                    # ── Clean and Classify ──
                    # This writes files into std_input/, RS_input/, sir_input/, etc.
                    # It uses the chunk's filename so they are saved correctly as _part_.
                    stats = clean_and_classify(rows, str(chunk_path), original_headers)
                    
                    # If this was a newly created chunk, delete it after classification
                    if str(chunk_path) != filepath:
                        os.remove(str(chunk_path))

                # ── Archive or Delete based on file type ──
                # We only archive "Original" files. "Decomposed" parts (_batch_) 
                # are deleted to keep the ARCHIVE clean.
                if "_batch_" in filename:
                    if file_path.exists():
                        os.remove(file_path)
                    logger.info(f"✅ [Phase 1] Done! Decomposed part deleted (not archived). Buckets updated.")
                else:
                    archive_dir = Path(config.ARCHIVE_DIR)
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    dest_path = archive_dir / filename
                    
                    # Handle filename collisions in archive
                    if dest_path.exists():
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        dest_path = archive_dir / f"{timestamp}_{filename}"
                    
                    shutil.move(file_path, dest_path)
                    logger.info(f"✅ [Phase 1] Done! Original archived. Buckets updated.")

                # Delete sidecar metadata if it was generated
                meta_path = chunker._get_metadata_path(file_path)
                if meta_path.exists():
                    os.remove(meta_path)
                
            except Exception as e:
                logger.error(f"  ❌ Error pre-processing {filename}: {e}", exc_info=True)

def ensure_dirs():
    """Ensure all required directories exist before starting."""
    dirs = [
        config.WORK_DIR,
        config.INCOMING_DIR,
        config.INPUT_STD_DIR,
        config.INPUT_RS_DIR,
        config.INPUT_SIR_DIR,
        config.INPUT_OTHER_DIR,
        config.ARCHIVE_BACKUP_DIR,
        config.LOG_DIR,
    ]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
            logger.debug(f"[Setup] Created directory: {d}")

if __name__ == "__main__":
    ensure_dirs()
    
    # Pre-process any existing files in incoming/
    logger.info("Scanning for existing files in incoming/...")
    handler = RawFileHandler()
    incoming_dir = Path(config.INCOMING_DIR)
    if incoming_dir.exists():
        for f in incoming_dir.iterdir():
            if not f.name.startswith((".", "~")):
                handler.handle_event(str(f))

    # Start Watchdog
    observer = Observer()
    observer.schedule(handler, path=config.INCOMING_DIR, recursive=False)
    
    logger.info(f"♾️  Pre-Processor started. Watching {config.INCOMING_DIR} 24/7...")
    try:
        observer.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("Stopped by user.")
    observer.join()
