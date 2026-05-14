# Implementation Plan

## Performance Root Cause Analysis

**PROBLEM**: 16 rows took 3h16m (~12.25 min/row avg)

### Root Causes

1. **BLOCKING SLEEPS** - time.sleep(8s) in Layer 2 nodes blocks async loop
2. **Circuit Breaker** - 300s pause when threshold reached
3. **8s Tier Cooldown** - Every tier failure adds 8 seconds
4. **Soft-Retry 3s** - Adds delay per empty search result
5. **Browser Startup** - Up to 90s per tier in Docker
6. **Typing Delays** - 0.04-0.16s per character

### FIXES APPLIED

1. [x] **Layer2 nodes**: time.sleep -> asyncio.run_in_executor + capped to 2s max
   - File: `src/agents/layer2/nodes.py`
   - Impact: Non-blocking sleep, doesn't stall event loop

2. [x] **Circuit breaker**: 300s -> 60s pause
   - File: `src/infra/browsers/hybrid_engine.py`
   - Impact: Max 60s instead of 5min pause

3. [x] **Tier cooldown**: 8s -> 3s
   - File: `src/infra/browsers/hybrid_engine.py`
   - Impact: Faster tier escalation

4. [x] **Typing delays**: Reduced 50%
   - File: `src/core/config.py`
   - Values: TYPING_MIN 0.04->0.02, TYPING_MAX 0.16->0.08

### Expected Performance Improvement

- Before: ~12.25 min/row
- Estimated after: ~3-5 min/row (60-70% faster)

### Recommendations for Further Optimization

1. Consider setting `PERFORMANCE_MODE=simple` to reduce tiers
2. Disable Layer 2 if not needed (set `LAYER2_ENABLED=false`)
3. Increase Docker Desktop RAM to 8GB+ for better Chrome performance
