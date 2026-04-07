import time
from typing import Dict, Any

class PerformanceTracker:
    """Tracks processing times and computes metrics for file and row-level operations."""

    def __init__(self):
        self.file_start_time = None
        self.file_end_time = None
        self.rows_processed = 0
        self.rows_done = 0
        self.total_row_duration = 0.0

    def start_file_processing(self):
        self.file_start_time = time.perf_counter()

    def end_file_processing(self):
        self.file_end_time = time.perf_counter()

    def track_row(self, duration: float, status: str):
        self.rows_processed += 1
        self.total_row_duration += duration
        if status == "DONE":
            self.rows_done += 1

    def get_metrics_summary(self) -> Dict[str, Any]:
        if not self.file_start_time or not self.file_end_time:
            total_time = 0.0
        else:
            total_time = round(self.file_end_time - self.file_start_time, 2)
            
        success_rate = (self.rows_done / self.rows_processed * 100) if self.rows_processed > 0 else 0.0
        avg_row_time = (self.total_row_duration / self.rows_processed) if self.rows_processed > 0 else 0.0

        return {
            "total_execution_seconds": total_time,
            "average_row_seconds": round(avg_row_time, 2),
            "rows_processed": self.rows_processed,
            "success_rate_percent": round(success_rate, 2)
        }

    def format_console_report(self) -> str:
        metrics = self.get_metrics_summary()
        return (
            f"⏱️  Performance Report ⏱️\n"
            f"   Total elapsed: {metrics['total_execution_seconds']}s\n"
            f"   Avg row speed: {metrics['average_row_seconds']}s / row\n"
            f"   Success rate : {metrics['success_rate_percent']}% ({self.rows_done}/{metrics['rows_processed']} done)"
        )
