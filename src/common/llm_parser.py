"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/llm_parser.py                                                     ║
║                                                                          ║
║  Intelligent Schema & Column Detector using Local LLMs (Prompt+Thinking)║
║  Used when heuristics fail or headless CSVs are encountered.             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import logging
from typing import Dict, List, Optional
from infra.intelligence.ollama_client import ollama_client

logger = logging.getLogger(__name__)

LLM_SCHEMA_SYSTEM_PROMPT = """You are a French Data Specialist organizing B2B contact lists.
Your task is to identify which column index (0-based) represents specific fields.
The fields we need are: "raison_sociale", "adresse", "siren", "telephone".
Data often lacks headers or has missing spaces in header names (e.g. "raisonsociale", "codepostal").
We will provide you with the first 3 rows of data. 

Use a `<thought>` block to reason about the contents of each column index. Explain column by column.
Then, supply the mapping strictly as a JSON object mapping the desired fields to the correct integer index.
If a concept is entirely missing, map it to `null`.

### Expected Format:
<thought>
Col 0: "Google France" -> looks like the company name (raison_sociale).
Col 1: "81 rue de Paris, 75001" -> physical location (adresse).
Col 2: "732829320" -> 9-digit string indicating a SIREN.
Col 3: "01 22 33 44 55" -> phone number (telephone).
</thought>
```json
{
  "raison_sociale": 0,
  "adresse": 1,
  "siren": 2,
  "telephone": 3
}
```
"""

async def detect_columns_with_llm(headers: List[str], sample_rows: List[List[str]]) -> Dict[str, Optional[str]]:
    """
    Uses the local LLM to infer the column mapping contextually.
    Takes headers (which might just be ['col_1', 'col_2']) and first 3 rows.
    Returns standard mapping format e.g. {"raison_sociale": "col_1", ...}.
    """
    if not sample_rows:
        return {}

    # Format the data for the prompt
    data_str = "HEADERS: " + " | ".join([str(h) for h in headers]) + "\n\nDATA ROWS:\n"
    for idx, row in enumerate(sample_rows[:3]):
        data_str += f"Row {idx+1}: " + " | ".join([f"[{i}] {str(val)}" for i, val in enumerate(row)]) + "\n"

    prompt = f"{LLM_SCHEMA_SYSTEM_PROMPT}\n\nHere is the data:\n{data_str}"

    logger.info("[LLM Parser] Initiating generative schema extraction...")
    
    try:
        response_text = await ollama_client.complete(prompt)
        if not response_text:
            return {}

        # Extract JSON from response
        # Find everything between `{` and `}` that forms the final JSON logic
        start_idx = response_text.rfind('{')
        end_idx = response_text.rfind('}')
        if start_idx == -1 or end_idx == -1:
            logger.error("[LLM Parser] No JSON structure found in output.")
            return {}
            
        json_str = response_text[start_idx:end_idx+1]
        raw_mapping = json.loads(json_str)
        
        # Convert index integers back to the local header names
        final_mapping = {}
        target_keys = ["raison_sociale", "adresse", "siren", "telephone"]
        
        for k in target_keys:
            idx = raw_mapping.get(k)
            if isinstance(idx, int) and 0 <= idx < len(headers):
                final_mapping[k] = headers[idx]
            else:
                final_mapping[k] = None

        logger.info(f"[LLM Parser] Success. Gen-AI Mapping: {final_mapping}")
        return final_mapping

    except json.JSONDecodeError:
        logger.error("[LLM Parser] Failed to parse generated schema JSON.")
    except Exception as e:
        logger.error(f"[LLM Parser] AI inference failed: {str(e)}")
        
    return {}
