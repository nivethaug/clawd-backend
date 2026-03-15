# ACPX Process Crash Investigation

## Recent Crash Pattern (March 15, 2026)

### Observed Symptoms:
```
🔴 ACPX-V2-STEP13-BATCH-FAIL: Logs - SIGABRT (-6): Process aborted/crashed
🔴 ACPX-V2-STEP13-BATCH-FAIL: Schedules - SIGABRT (-6): Process aborted/crashed
🔴 ACPX-V2-STEP13-BATCH-FAIL: Jobs - (interrupted by server restart)
```

### Error Code Analysis:

**SIGABRT (-6)** - Process aborted/crashed
- Indicates the process called `abort()` or received SIGABRT signal
- Common causes:
  1. **Claude API Rate Limiting** (Most Likely)
  2. Claude API Authentication Failure
  3. Out of Memory (OOM)
  4. Unrecoverable Internal Error
  5. Assertion Failure in ACPX
  6. Network Timeout/Error

## Potential Causes:

### 1. Claude API Rate Limiting (HIGH PROBABILITY)

**Evidence:**
- Multiple pages failing in quick succession
- All failures with same error code (-6)
- Timing suggests rate limit window exhaustion

**Claude API Limits:**
- Tier 1: 6 requests per minute
- Tier 2: 30 requests per minute
- Tier 3: 60 requests per minute

**What Happens:**
```python
# ACPX makes API call
response = claude_api.generate(prompt)

# Claude API returns 429 Too Many Requests
# ACPX process crashes with SIGABRT
```

**Solution:**
```python
# Add rate limit detection and backoff
if result.returncode == -6:
    # Check if rate limit
    if "rate limit" in stderr.lower():
        logger.warning("Rate limit detected, waiting 60s...")
        time.sleep(60)
        # Retry with backoff
```

### 2. Claude API Authentication Failure (MEDIUM PROBABILITY)

**Evidence:**
- Server restart mid-execution
- GROQ_API_KEY lost after restart
- Environment variables not persisted

**What Happens:**
```python
# After server restart
os.environ.get("GROQ_API_KEY")  # Returns None or invalid

# ACPX tries to use invalid key
# Claude API returns 401 Unauthorized
# ACPX crashes with SIGABRT
```

**Solution:**
```python
# Validate environment before ACPX
def validate_api_keys():
    if not os.getenv("GROQ_API_KEY"):
        raise ValueError("GROQ_API_KEY not set")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY not set")
```

### 3. Out of Memory (LOW-MEDIUM PROBABILITY)

**Evidence:**
- Large prompts (page descriptions + specifications)
- Multiple concurrent processes
- Server restart could indicate OOM

**What Happens:**
```python
# Large prompt size
prompt_size = len(page_prompt)  # Could be 5-10KB

# ACPX loads Claude response into memory
response_size = 50-100KB per page

# Multiple pages = memory exhaustion
# Process killed with SIGABRT
```

**Solution:**
```python
# Check available memory before batch
import psutil

def check_memory():
    mem = psutil.virtual_memory()
    if mem.available < 500 * 1024 * 1024:  # Less than 500MB
        logger.warning("Low memory, waiting...")
        time.sleep(30)
```

### 4. Large Prompt Size (MEDIUM PROBABILITY)

**Evidence:**
- Page prompts include full descriptions
- Mock data requirements
- UI specifications

**What Happens:**
```python
# Prompt too large for Claude API
prompt_tokens = count_tokens(page_prompt)  # Could exceed 100K

# Claude API rejects request
# ACPX crashes with SIGABRT
```

**Solution:**
```python
# Truncate or simplify prompts
MAX_PROMPT_SIZE = 8000  # characters

if len(page_prompt) > MAX_PROMPT_SIZE:
    page_prompt = page_prompt[:MAX_PROMPT_SIZE]
    logger.warning(f"Prompt truncated to {MAX_PROMPT_SIZE} chars")
```

### 5. Concurrent Request Limits (MEDIUM PROBABILITY)

**Evidence:**
- Batch population runs multiple ACPX sequentially
- Each page = 1 API call
- Could hit concurrent limits

**What Happens:**
```python
# Multiple ACPX processes running
process1 = subprocess.run(["acpx", ...])  # Logs
process2 = subprocess.run(["acpx", ...])  # Schedules
process3 = subprocess.run(["acpx", ...])  # Jobs

# Claude API detects concurrent requests
# Rejects with rate limit error
# ACPX crashes with SIGABRT
```

**Solution:**
```python
# Add delay between batch operations
for page_name in empty_pages:
    success, error_info = populate_page(page_name, attempt=1)
    if not success:
        # Wait before next attempt
        time.sleep(5)  # 5 second delay
```

## Diagnostic Steps:

### 1. Check ACPX Logs
```bash
# Check if ACPX writes logs
ls -la ~/.acpx/logs/
cat ~/.acpx/logs/error.log
```

### 2. Capture Stderr/Stdout
```python
# Already implemented in enhanced failure reports
# Will show exact error from ACPX
```

### 3. Monitor API Usage
```python
# Add API call tracking
api_calls = []
api_calls.append({
    "timestamp": time.time(),
    "page": page_name,
    "prompt_size": len(page_prompt)
})

# Check rate before next call
recent_calls = [c for c in api_calls if time.time() - c['timestamp'] < 60]
if len(recent_calls) >= 5:
    logger.warning("Approaching rate limit, waiting...")
    time.sleep(60)
```

### 4. Test ACPX in Isolation
```bash
# Run ACPX manually to see exact error
acpx --cwd /path/to/frontend/src --format quiet claude exec "Test prompt"

# Check return code
echo $?
```

## Immediate Fixes:

### Fix 1: Add Rate Limit Detection
```python
def populate_page(page_name, attempt=1):
    try:
        # ... existing code ...
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        
        # Check for rate limit
        if result.returncode == -6:
            if result.stderr and "rate limit" in result.stderr.lower():
                logger.warning(f"Rate limit hit for {page_name}, waiting 60s...")
                time.sleep(60)
                # Retry once after waiting
                if attempt == 1:
                    return populate_page(page_name, attempt=2)
        
        # ... rest of error handling ...
```

### Fix 2: Add Delay Between Batch Calls
```python
# In batch population loop
for page_name in empty_pages:
    success, error_info = populate_page(page_name, attempt=1)
    if success:
        populated_count += 1
    else:
        failed_pages.append(page_name)
        if error_info:
            failure_reports.append(error_info)
    
    # Add delay to avoid rate limits
    time.sleep(3)  # 3 seconds between pages
```

### Fix 3: Validate Environment
```python
# Before starting batch operations
def validate_environment():
    """Validate all required environment variables."""
    required_vars = [
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        # Add other required vars
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        raise ValueError(f"Missing environment variables: {missing}")
```

### Fix 4: Graceful Error Recovery
```python
# Instead of crashing, log and continue
except subprocess.TimeoutExpired:
    logger.warning(f"Timeout for {page_name}, will retry in cycle 2")
    return False, {"error_type": "timeout", "page": page_name}

except Exception as e:
    logger.error(f"Unexpected error for {page_name}: {e}")
    return False, {"error_type": "exception", "page": page_name, "message": str(e)}
```

## Recommended Action Plan:

### Immediate (Now):
1. ✅ **Enhanced failure reports** - Already implemented
2. 🔄 **Add delay between batch calls** - 3-5 seconds
3. 🔄 **Rate limit detection** - Check stderr for "rate limit"
4. 🔄 **Environment validation** - Check API keys before starting

### Short Term (Next Run):
1. Monitor failure reports for exact error messages
2. Track API call timing to detect rate limits
3. Test with single page to isolate issue
4. Check ACPX logs if available

### Long Term:
1. Implement exponential backoff for retries
2. Add API quota tracking
3. Consider using streaming instead of batch
4. Implement partial save functionality

## Next Steps:

1. **Implement delay between batch calls** (3-5 seconds)
2. **Add rate limit detection** in populate_page function
3. **Validate environment variables** before batch operations
4. **Test with single page** to see if issue persists

---

**Document Version**: 1.0  
**Last Updated**: March 15, 2026  
**Status**: Investigation in progress - most likely Claude API rate limiting
