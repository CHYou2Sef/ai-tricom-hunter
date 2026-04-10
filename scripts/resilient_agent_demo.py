"""
╔══════════════════════════════════════════════════════════════════════════╗
║  scripts/resilient_agent_demo.py                                         ║
║                                                                          ║
║  A demonstration of the resilience features requested in GEMINI.md:     ║
║    ✓ Human-like delays                                                   ║
║    ✓ Log saturation prevention                                            ║
║    ✓ Large file decomposition with recovery                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import time
import json
import os
from pathlib import Path

from utils.anti_bot import human_delay, get_random_delay
from utils.logger import get_logger, verbose_logging
from utils.chunker import FileChunker

logger = get_logger("ResilientAgent")

def simulate_data_collection(file_path: str):
    """
    Simulates a 24/7 logging-heavy data collection task with chunks.
    """
    logger.info(f"Starting resilient collection for: {file_path}")

    # 1. Decomposition (Resilience)
    chunker = FileChunker(work_dir="logs/chunks_demo")
    
    # Simulate an existing file for demo purposes
    mock_file = Path(file_path)
    if not mock_file.exists():
        with open(mock_file, 'w') as f:
            json.dump([{"id": i, "data": "dummy"} for i in range(2500)], f)

    # 2. Chunking (Resilience)
    chunk_paths = chunker.split_json_list(file_path, chunk_size=500)
    
    # 3. Processing (Human-like Delays & Logging)
    for i, path in enumerate(chunk_paths):
        # Check recovery state
        if i < (chunker.get_next_pending_chunk(mock_file) or 0):
            logger.info(f"Skipping already completed chunk {i+1}")
            continue

        logger.info(f"Processing Chunk {i+1}/{len(chunk_paths)}: {path.name}")
        
        # Verbose logging ONLY for processing steps (Log Saturation Prevention)
        with verbose_logging():
            logger.debug(f"Opening {path.name}...")
            # Simulate work
            for _ in range(5):
                # Realistic human-like delay (Gaussian)
                human_delay(mean=0.5, std=0.1, min_sec=0.1, max_sec=2.0)
            
            logger.debug(f"Chunk {i+1} records processed successfully.")

        # Mark progress (Resilience)
        chunker.mark_chunk_done(mock_file, i)
        logger.info(f"Successfully checkpointed chunk {i+1}")

    logger.info("Task completed successfully. All components operational.")

if __name__ == "__main__":
    import config
    os.makedirs(config.INCOMING_DIR, exist_ok=True)
    simulate_data_collection(str(config.INCOMING_DIR / "raw_bulk_data.json"))
