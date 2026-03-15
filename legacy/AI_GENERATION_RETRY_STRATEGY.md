# AI Generation Retry Strategy

## How Replit and Lovable Handle AI Generation Failures

### Replit's Approach

**Multi-Stage Generation:**
1. **Initial Generation**: AI creates code with reasonable timeout (60-120s)
2. **Progressive Enhancement**: If generation fails, Replit:
   - Breaks task into smaller chunks
   - Retries with simpler prompts
   - Provides partial results with clear markers
   - Allows manual continuation

**Key Features:**
- **Streaming Output**: Shows progress in real-time
- **Partial Saves**: Saves what was generated before timeout
- **User Intervention**: Allows user to edit/continue if AI stalls
- **Intelligent Chunking**: Splits large files into sections
- **Context Preservation**: Maintains conversation context across retries

**Failure Handling:**
- Timeout → Retry with smaller scope
- Error → Retry with simpler prompt
- Max retries (3) → Return partial + user-friendly message
- Always provides actionable next steps

### Lovable's Approach

**Iterative Refinement:**
1. **Rapid Prototyping**: Quick first pass (30-60s)
2. **Incremental Improvement**: Multiple short cycles
3. **Progressive Enhancement**: Each cycle adds more detail

**Key Features:**
- **Short Bursts**: 30-60 second generation windows
- **Multiple Cycles**: 3-5 improvement passes
- **Quality Checks**: Validates code after each cycle
- **Adaptive Prompts**: Adjusts based on previous failures

**Failure Handling:**
- Timeout → Save progress, start next cycle
- Error → Retry with different approach
- Build failure → Auto-fix, then retry
- Graceful degradation → Ship what works

## Our Implementation

### Current Strategy

**Two-Cycle Approach:**

```
Cycle 1: First Pass
├─ Try all empty pages (150s timeout each)
├─ Collect failures with detailed reports
└─ Log: return codes, timeouts, exceptions

Cycle 2: Retry Failed Pages
├─ Retry each failed page once
├─ Track recovery rate
└─ Update failure reports

Final: Summary Report
├─ Success count: X/Y pages
├─ Failed pages: [list]
└─ Failure reports: [details]
```

### Comparison Table

| Feature | Replit | Lovable | Our System |
|---------|--------|---------|------------|
| **Timeout per cycle** | 60-120s | 30-60s | 150s |
| **Max retry cycles** | 3+ | 3-5 | 2 |
| **Partial saves** | ✅ Yes | ✅ Yes | ❌ No |
| **Streaming output** | ✅ Yes | ✅ Yes | ❌ No |
| **Failure reports** | ✅ Basic | ✅ Basic | ✅ Detailed |
| **Adaptive prompts** | ✅ Yes | ✅ Yes | ❌ No |
| **Progressive enhancement** | ✅ Yes | ✅ Yes | ❌ No |
| **Build integration** | ❌ No | ✅ Yes | ✅ Yes |
| **Autonomous fix loop** | ❌ No | ✅ Yes | ✅ Yes |

### Advantages of Our Approach

✅ **Detailed Failure Reports**: 
- Error type classification (timeout/return_code/exception)
- Stderr/stdout capture (first 500 chars)
- Attempt tracking
- Command details

✅ **Resilient Pipeline**:
- Continues even if pages fail
- Build loop handles compilation errors
- Graceful degradation

✅ **Clear Metrics**:
- Populated count: X/Y
- Retry success rate
- Failed pages list

### Areas for Improvement

❌ **No Partial Saves**: 
- If timeout occurs at 140s, we lose all progress
- Replit/Lovable save partial results

❌ **No Streaming**:
- Can't see progress in real-time
- Harder to debug long-running operations

❌ **Fixed Prompts**:
- Same prompt on retry (not adaptive)
- Could simplify on second attempt

❌ **Long Timeouts**:
- 150s per page vs 30-60s industry standard
- Higher risk of wasted time

## Recommended Enhancements

### Priority 1: Partial Saves (High Impact)

```python
# Save progress periodically
if elapsed_time > 120 and partial_content:
    save_partial_page(page_name, partial_content)
    logger.info(f"Saved partial content for {page_name}")
```

**Benefit**: Recover from timeouts without complete loss

### Priority 2: Adaptive Prompts (Medium Impact)

```python
# Simplify prompt on retry
if attempt == 2:
    page_prompt = f"""Create a basic {page_name} page:
    - Simple layout with Tailwind
    - Basic mock data (2-3 items)
    - ~80-100 lines
    Focus on working code over features."""
```

**Benefit**: Higher success rate on retry

### Priority 3: Streaming Output (Medium Impact)

```python
# Stream output for visibility
process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
for line in process.stdout:
    print(f"🔴 ACPX-V2-STREAM: {line}")
```

**Benefit**: Real-time progress visibility

### Priority 4: Shorter Cycles (Lower Priority)

```python
# Reduce timeout, increase cycles
timeout = 90  # Shorter per-cycle timeout
max_cycles = 3  # More retry opportunities
```

**Benefit**: Faster failure detection, less wasted time

## Current Best Practices

Based on Replit and Lovable's approaches, our system should:

1. ✅ **Fail Gracefully**: Continue pipeline even if pages fail
2. ✅ **Collect Diagnostics**: Detailed failure reports for debugging
3. ✅ **Retry Once**: Second attempt for failed pages
4. ✅ **Clear Communication**: PM2 logs show progress clearly
5. ✅ **Integration**: Works with autonomous build fix loop

## Next Steps

1. **Implement Partial Saves**: Save generated code before timeout
2. **Add Adaptive Prompts**: Simplify prompts on retry
3. **Consider Streaming**: Real-time output for long operations
4. **Monitor Metrics**: Track retry success rates over time
5. **A/B Test Timeouts**: Compare 150s vs 90s with retry

## Metrics to Track

- First pass success rate: % of pages populated on first try
- Retry recovery rate: % of failed pages that succeed on retry
- Average generation time: Mean time per page
- Timeout frequency: How often 150s timeout is hit
- Failure types: Distribution of timeout vs error vs return_code

---

**Document Version**: 1.0  
**Last Updated**: March 15, 2026  
**Status**: Implemented - Two-cycle retry with failure reports
