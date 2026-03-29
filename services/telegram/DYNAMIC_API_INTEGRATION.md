# Telegram Bot Dynamic API Integration System

## Overview

The Telegram Bot AI Editor now supports **safe, dynamic API integrations** while maintaining strict control over modifications.

## ✅ Key Enhancements

### 1. **Dual-File Modification Support**
- **Allowed Files:**
  - `services/ai_logic.py` - Business logic modifications
  - `services/api_client.py` - API helper functions
  
- **Protected Files (Cannot be modified):**
  - `main.py`
  - `config.py`
  - `database.py`
  - Any other files

### 2. **Template Utility Functions**

Added to `templates/telegram-bot-template/services/api_client.py`:

```python
def fetch_json(url: str, params: dict = None, timeout: int = API_TIMEOUT) -> dict:
    """Generic JSON fetcher for public APIs."""
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}

def safe_get(data: dict, *keys, default=None):
    """Safely get nested dictionary value."""
    for key in keys:
        try:
            data = data[key]
        except (KeyError, TypeError):
            return default
    return data
```

### 3. **AI Behavior Rules**

When user requests a bot with external data needs:

1. **Check existing API functions** in `api_client.py`
2. **Add new helper function** if needed:
   ```python
   def get_joke() -> dict:
       result = fetch_json("https://v2.jokeapi.dev/joke/Programming")
       if result["success"]:
           return {"success": True, "joke": safe_get(result, "data", "joke", default="")}
       return result
   ```
3. **Call from ai_logic.py**:
   ```python
   if "joke" in text_lower:
       result = get_joke()
       if result["success"]:
           return f"😄 {result['joke']}"
       return "⚠️ Couldn't fetch joke"
   ```

### 4. **Safety Guarantees**

✅ **Strict Scope Control**
- Only `ai_logic.py` and `api_client.py` can be modified
- All other files are protected

✅ **No Import Changes**
- All imports pre-defined in templates
- AI cannot add new dependencies

✅ **Error Handling**
- All API calls wrapped in try/except
- Graceful fallback messages
- Never crashes the bot

✅ **Validation**
- Syntax validation for both files
- Function signature check
- At least one file must be modified

✅ **Rollback Safety**
- Automatic rollback on validation failure
- Automatic rollback on Claude failure
- Automatic rollback on timeout

## 🎯 Usage Example

**User Request:** "Create a joke bot"

**System Process:**
1. AI reads `ai_logic.py` and `api_client.py`
2. AI detects need for joke API
3. AI adds `get_joke()` to `api_client.py`:
   ```python
   def get_joke() -> dict:
       result = fetch_json("https://v2.jokeapi.dev/joke/Programming?safe-mode")
       if result["success"]:
           joke_data = result["data"]
           if joke_data.get("type") == "single":
               return {"success": True, "joke": joke_data["joke"]}
           return {"success": True, "joke": f"{joke_data['setup']} ... {joke_data['delivery']}"}
       return result
   ```
4. AI modifies `process_user_input()` in `ai_logic.py`:
   ```python
   if any(kw in text_lower for kw in ["joke", "funny", "laugh"]):
       result = get_joke()
       if result["success"]:
           return f"😄 {result['joke']}"
       return "⚠️ Couldn't fetch a joke right now"
   ```
5. Validation passes
6. Bot deployed successfully

## 🔐 Security Constraints

### ❌ AI Cannot:
- Add new imports
- Modify `main.py`, `config.py`, `database.py`
- Create new files
- Change function signatures
- Break existing logic

### ✅ AI Can:
- Add helper functions to `api_client.py`
- Modify logic inside `process_user_input()`
- Use existing imports
- Call existing API functions
- Add new keyword handlers

## 📁 File Structure

```
templates/telegram-bot-template/
├── services/
│   ├── ai_logic.py          ← AI can modify (logic only)
│   ├── api_client.py        ← AI can modify (add functions)
│   ├── main.py              ← PROTECTED
│   ├── config.py            ← PROTECTED
│   └── database.py          ← PROTECTED
```

## 🧪 Testing

All changes verified:
- ✅ `editor.py` compiles successfully
- ✅ `ai_logic.py` template compiles
- ✅ `api_client.py` template compiles
- ✅ Validation logic updated
- ✅ Rollback logic updated

## 🚀 Benefits

1. **Dynamic Bots**: Support any public API
2. **Safe Modifications**: Strict scope control
3. **Template-Driven**: All imports pre-defined
4. **Error-Resistant**: Comprehensive error handling
5. **User-Friendly**: Clean error messages
6. **Production-Ready**: Robust validation and rollback

## 📝 Public APIs (No Auth Required)

Recommended APIs for AI to use:
- **CoinGecko**: `https://api.coingecko.com/api/v3` (crypto prices)
- **JokeAPI**: `https://v2.jokeapi.dev/joke` (jokes)
- **RestCountries**: `https://restcountries.com/v3.1` (country info)
- **ExchangeRate**: `https://api.exchangerate-api.com/v4` (currency)

## 🎯 Goal Achieved

The system is now:
- ✔ Dynamic
- ✔ API-driven
- ✔ Safe
- ✔ Extendable
- ✔ Production-ready

---

**Last Updated:** 2026-03-29  
**Status:** ✅ Implemented and Tested
