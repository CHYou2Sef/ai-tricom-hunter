import os
import gzip
import shutil
import time
from pathlib import Path

# Add project root to path for config import
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

def compress_oversized_logs(limit_mb: int = 10):
    """
    Scans the logs directory and compresses any .log file larger than limit_mb.
    """
    log_dir = Path(config.LOG_DIR)
    if not log_dir.exists():
        print(f"❌ Log directory not found at {log_dir}")
        return

    limit_bytes = limit_mb * 1024 * 1024
    compressed_count = 0

    print(f"🔍 Scanning {log_dir} for logs > {limit_mb}MB...")

    for log_file in log_dir.glob("*.log"):
        # Skip hidden or active lock files
        if log_file.name.startswith("."): continue
        
        file_size = log_file.stat().st_size
        if file_size > limit_bytes:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            gz_path = log_dir / f"{log_file.stem}_{timestamp}.log.gz"
            
            print(f"📦 Compressing {log_file.name} ({file_size // (1024*1024)}MB) -> {gz_path.name}")
            
            try:
                with open(log_file, 'rb') as f_in:
                    with gzip.open(gz_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # We truncate the original file instead of deleting it 
                # to avoid breaking active file handles from the logger.
                with open(log_file, 'w') as f:
                    f.truncate(0)
                
                print(f"✅ Successfully compressed and cleared {log_file.name}")
                compressed_count += 1
            except Exception as e:
                print(f"❌ Failed to compress {log_file.name}: {e}")

    print(f"🏁 Done. Compressed {compressed_count} file(s).")

if __name__ == "__main__":
    compress_oversized_logs(limit_mb=10)
