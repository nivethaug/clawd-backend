# Unit Tests for Telegram Bot

This folder contains automated unit tests for Telegram bot functionality.

## Purpose

Unit tests verify that:
- Commands are registered correctly
- Handlers process messages as expected
- **REAL API calls work** (not just mocks)
- Responses match expected output from actual data sources
- Edge cases are handled properly

## Running Tests

### All Tests
```bash
cd /path/to/your/bot
python -m pytest unit/ -v
```

### Specific Test File
```bash
python -m pytest unit/test_commands.py -v
python -m pytest unit/test_handlers.py -v
```

### Run with Coverage
```bash
python -m pytest unit/ --cov=. --cov-report=html
```

## Test Files

### `test_commands.py`
Tests for bot commands:
- `/start` command registration and response
- `/help` command command list display
- `/status` command status reporting
- Custom commands with **real API calls**
- Command parsing and validation
- **Real API responses** (weather, crypto, news, etc.)

### `test_handlers.py`
Tests for message handlers:
- Text message processing
- Command message filtering
- Message logging
- Edge cases (empty messages, special characters)
- **Real API integration** through ai_logic.py

## Testing Philosophy - REAL APIs

### Use Real APIs (Primary)
Tests should use ACTUAL API endpoints from `/llm/categories/`:
- `/llm/categories/weather.json` → Open-Meteo API
- `/llm/categories/crypto_finance.json` → CoinGecko API
- `/llm/categories/news.json` → Hacker News API
- `/llm/categories/food.json` → Food API

**Why Real APIs?**
- ✅ Verifies integration actually works
- ✅ Catches API contract changes
- ✅ Tests actual data flow end-to-end
- ✅ No false positives from outdated mocks

### When to Mock (Limited)
Only mock in these specific scenarios:
- **API timeout/failure testing**: Simulate network errors
- **Invalid input handling**: Test edge cases with invalid data
- **Rate limiting**: Test bot behavior when API limits reached
- **Error recovery**: Verify bot handles API failures gracefully

**Mock Rules:**
- ✅ Mock ONLY for failure scenarios (timeouts, 500 errors)
- ❌ NEVER mock successful API responses
- ❌ NEVER mock data that should come from real APIs
- ✅ Always verify with real APIs when possible

### Test Coverage Goals

- ✅ Commands parse correctly
- ✅ **API calls work with real endpoints** from `/llm/categories/`
- ✅ Error handling works (API failures, timeouts, invalid inputs)
- ✅ New commands don't break existing ones
- ✅ Integration between ai_logic.py and api_client.py works
- ✅ Real data is returned from public APIs

1. Create test file in `unit/` folder
2. Import the function/handler to test
3. Create test functions with `@pytest.mark.asyncio` decorator
4. Use `AsyncMock` for Telegram objects (Update, ContextTypes)
5. Assert expected behavior with `assert` statements

## Common Test Patterns

### Testing with Real APIs (PREFERRED)
```python
import pytest
from unittest.mock import AsyncMock, patch
from telegram import Update
from telegram.ext import ContextTypes

class TestRealAPIs:
    """Test real API integration."""
    
    @pytest.mark.asyncio
    async def test_price_command_real_api(self):
        """Test /price with REAL CoinGecko API."""
        from handlers.commands import price_command
        
        # Setup
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.text = AsyncMock(return_value="/price bitcoin")
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        # Execute command (makes REAL API call)
        await price_command(update, context)
        
        # Verify response (NOT mocked - real data)
        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        
        # Assert real data was returned (has $ or BTC)
        assert "$" in response or "BTC" in response
        assert "bitcoin" in response.lower() or "btc" in response.lower()
    
    @pytest.mark.asyncio
    async def test_weather_command_real_api(self):
        """Test /weather with REAL Open-Meteo API."""
        from handlers.commands import weather_command
        
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.text = AsyncMock(return_value="/weather London")
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await weather_command(update, context)
        
        # Verify real weather data
        response = update.message.reply_text.call_args[0][0]
        assert "°C" in response or "°F" in response
        assert "London" in response
```

### Testing API Failure Handling (MOCK OK)
```python
import pytest
from unittest.mock import AsyncMock, patch

class TestAPIFailures:
    """Test API error handling."""
    
    @pytest.mark.asyncio
    async def test_api_timeout(self):
        """Test API timeout error handling."""
        from handlers.commands import price_command
        
        # MOCK only for failure scenario (real API times out)
        with patch('services.api_client.get_crypto_price') as mock_api:
            mock_api.side_effect = TimeoutError("API timeout after 30s")
            
            update = Update(update_id=1)
            update.message = AsyncMock()
            update.message.text = AsyncMock(return_value="/price bitcoin")
            update.message.reply_text = AsyncMock()
            context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
            
            await price_command(update, context)
            
            # Verify error message
            response = update.message.reply_text.call_args[0][0]
            assert "error" in response.lower() or "try again" in response.lower()
            assert "timeout" in response.lower()
    
    @pytest.mark.asyncio
    async def test_api_500_error(self):
        """Test API server error handling."""
        from handlers.commands import price_command
        
        with patch('services.api_client.get_crypto_price') as mock_api:
            mock_api.side_effect = Exception("HTTP 500 - Server error")
            
            update = Update(update_id=1)
            update.message = AsyncMock()
            update.message.text = AsyncMock(return_value="/price bitcoin")
            response = update.message.reply_text.call_args[0][0]
            assert "error" in response.lower() or "service unavailable" in response.lower()
```

## Requirements

Install test dependencies:
```bash
pip install pytest pytest-asyncio pytest-cov
```

- **Fast**: Run in milliseconds (no need for manual Telegram testing)
- **Reliable**: Test all edge cases automatically
- **Continuous**: Can be run in CI/CD pipelines
- **Isolated**: Tests don't affect production bot
- **Clear**: Immediate pass/fail feedback
- **Real Integration**: Verifies actual API endpoints work

## When to Write Unit Tests

✅ DO write unit tests for:
- New commands
- New handlers
- Critical business logic
- Bug fixes
- API endpoint integration
- Real API calls from `/llm/categories/`

❌ DON'T write unit tests for:
- Simple CRUD operations (use integration tests)
- Third-party library code (assume they work)
- One-off scripts

Install pytest dependencies:
```bash
pip install pytest pytest-asyncio pytest-cov
```

## Benefits of Unit Tests

- **Fast**: Run in milliseconds (no need for manual Telegram testing)
- **Reliable**: Test all edge cases automatically
- **Continuous**: Can be run in CI/CD pipelines
- **Isolated**: Tests don't affect production bot
- **Clear**: Immediate pass/fail feedback

## When to Write Unit Tests

✅ DO write unit tests for:
- New commands
- New handlers
- Critical business logic
- Bug fixes
- API endpoints

❌ DON'T write unit tests for:
- Simple CRUD operations (use integration tests)
- Third-party library code (assume they work)
- One-off scripts

## Continuous Integration

These tests should run automatically after code changes to catch issues early.
