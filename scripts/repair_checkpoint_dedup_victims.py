#!/usr/bin/env python3
"""
repair_checkpoint_dedup_victims.py
───────────────────────────────────
One-shot repair for checkpoint files where rows were incorrectly marked
"NO TEL" due to GLOBAL_PHONE_SET dedup collisions but a valid phone is
present in phone_list.

For each such row:
  • Promotes the best phone (highest score) from phone_list → phone
  • Sets status = DONE
  • Writes a DUPLICATE_RESCUED marker for audit

Usage:
    python scripts/repair_checkpoint_dedup_victims.py [checkpoint.json ...]
    # Or run without args to process ALL checkpoint files in WORK/CHECKPOINTS/
"""
import sys
import json
import re
import shutil
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("repair")

# ── French phone validation (inline to avoid import issues) ──────────────────
_BLOCKED = {"0000000000", "1234567890", "0123456789", "0800000000"}

def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 9 and not digits.startswith("0"):
        digits = "0" + digits
    if len(digits) != 10:
        return None
    return digits

def is_valid(p: str | None) -> bool:
    if not p:
        return False
    d = re.sub(r"\D", "", p)
    if len(d) == 9 and not d.startswith("0"):
        d = "0" + d
    if len(d) != 10:
        return False
    if d in _BLOCKED:
        return False
    if not d.startswith("0"):
        return False
    return True


def repair_file(path: Path) -> dict:
    """Repair one checkpoint JSON. Returns stats dict."""
    stats = {"rescued": 0, "already_ok": 0, "skipped_bad_phone": 0, "total_no_tel": 0}

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Skip non-row files (e.g. GLOBAL_PHONE_SET.json which is a list)
    if not isinstance(data, dict):
        log.info(f"  ⏭️  Skipping {path.name} — not a row-keyed checkpoint dict.")
        return stats

    modified = False
    for key, entry in data.items():
        if key.startswith("__") or not isinstance(entry, dict):
            continue
        if entry.get("status") != "NO TEL":
            continue

        stats["total_no_tel"] += 1

        phone_list: list = entry.get("phone_list", [])
        if not phone_list:
            continue  # genuinely not found; leave as-is

        # Already has phone — was rescued in a previous run
        if entry.get("phone") and is_valid(entry.get("phone")):
            stats["already_ok"] += 1
            continue

        # Sort by score desc, pick best valid candidate
        best_candidate = None
        for candidate in sorted(phone_list, key=lambda x: x.get("score", 0), reverse=True):
            num = normalize_phone(candidate.get("num", ""))
            if num and is_valid(num):
                best_candidate = (num, candidate.get("score", 0), candidate.get("source", "?"))
                break

        if not best_candidate:
            log.warning(f"  Row {key}: phone_list has entries but none valid — skipping")
            stats["skipped_bad_phone"] += 1
            continue

        phone, score, source = best_candidate
        log.info(
            f"  ✅ Rescuing row {key}: {phone!r} "
            f"(score={score}, source={source}) → DONE"
        )
        entry["phone"] = phone
        entry["status"] = "DONE"
        entry["_rescue_meta"] = {
            "rescued_at": datetime.now().isoformat(),
            "rescued_from": "phone_list",
            "original_status": "NO TEL",
            "original_score": score,
            "original_source": source,
        }
        stats["rescued"] += 1
        modified = True

    if modified:
        # Backup original before overwriting
        backup = path.with_suffix(f".pre_rescue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
        shutil.copy2(path, backup)
        log.info(f"  📦 Backup → {backup.name}")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"  💾 Saved repaired checkpoint: {path.name}")
    else:
        log.info(f"  ℹ️  No changes needed for {path.name}")

    return stats


def main():
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        checkpoint_dir = Path("WORK/CHECKPOINTS")
        if not checkpoint_dir.exists():
            log.error("WORK/CHECKPOINTS directory not found. Run from project root.")
            sys.exit(1)
        paths = sorted(checkpoint_dir.glob("*.json"))

    if not paths:
        log.warning("No checkpoint files found.")
        sys.exit(0)

    total_rescued = 0
    for p in paths:
        log.info(f"\n📂 Processing: {p.name}")
        try:
            s = repair_file(p)
            log.info(
                f"  → total NO TEL: {s['total_no_tel']} | "
                f"rescued: {s['rescued']} | "
                f"skipped (bad phone): {s['skipped_bad_phone']}"
            )
            total_rescued += s["rescued"]
        except Exception as e:
            log.error(f"  Failed to repair {p}: {e}")

    log.info(f"\n✅ Done. Total rows rescued: {total_rescued}")


if __name__ == "__main__":
    main()
