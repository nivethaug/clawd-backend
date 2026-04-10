# Unit Tests

## Running Tests

```bash
# Run all tests
python -m pytest unit/ -v

# Or with unittest
python -m unittest discover unit/ -v
```

## Test Files

| File | Tests |
|------|-------|
| `test_commands.py` | AI logic processing, intent detection, fallbacks |
| `test_handlers.py` | API client functions, mock data responses |

## Adding New Tests

1. Create `unit/test_<feature>.py`
2. Import the module to test
3. Use `unittest.TestCase` or `pytest`
4. Mock external dependencies (API calls, DB connections)
