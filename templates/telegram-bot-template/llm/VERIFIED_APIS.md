# Verified APIs - Quick Reference

**Last Verified:** April 1, 2026  
**Method:** Chrome DevTools MCP Live Testing

## ✅ Fully Operational APIs (No Auth Required)

### Weather & Climate
- **Open-Meteo** - `https://api.open-meteo.com/v1/forecast`
  - ✅ No authentication
  - ✅ Fast response
  - ✅ Reliable
  - Endpoint: `/weather/open-meteo`

### Currency & Finance
- **Frankfurter** - `https://api.frankfurter.app/latest`
  - ✅ No authentication
  - ✅ Daily updates
  - ✅ Multiple currencies
  - Endpoint: `/currency/rates`

- **CoinGecko** - `https://api.coingecko.com/api/v3/`
  - ✅ No authentication (rate limited)
  - ✅ Cryptocurrency data
  - Endpoint: `/finance/crypto/coingecko`

### Entertainment
- **JokeAPI** - `https://v2.jokeapi.dev/joke/Any`
  - ✅ No authentication
  - ✅ Safe mode available
  - ✅ Multiple categories
  - Endpoint: `/entertainment/jokes`

- **Chuck Norris API** - `https://api.chucknorris.io/jokes/random`
  - ✅ No authentication
  - ✅ Random facts
  - Endpoint: `/entertainment/chuck-norris`

### Knowledge & Education
- **Free Dictionary API** - `https://api.dictionaryapi.dev/api/v2/entries/en/`
  - ✅ No authentication
  - ✅ Comprehensive definitions
  - ✅ Phonetic data
  - Endpoint: `/knowledge/dictionary`

- **Hacker News** - `https://hacker-news.firebaseio.com/v0/`
  - ✅ No authentication
  - ✅ Real-time data
  - Endpoint: `/news/hackernews`

### Science & Space
- **SpaceX API** - `https://api.spacexdata.com/v4/`
  - ✅ No authentication
  - ✅ Comprehensive launch data
  - Endpoint: `/science/spacex`

### Development & Testing
- **JSONPlaceholder** - `https://jsonplaceholder.typicode.com/`
  - ✅ No authentication
  - ✅ Perfect for testing
  - Endpoint: `/ecommerce/posts`, `/ecommerce/users`

- **DummyJSON** - `https://dummyjson.com/`
  - ✅ No authentication
  - ✅ 100 products available
  - Endpoint: `/ecommerce/dummy/products`

### Animals
- **Dog CEO** - `https://dog.ceo/api/`
  - ✅ No authentication
  - ✅ Random dog images
  - Endpoint: `/images/dogceo/random`

- **Cataas** - `https://cataas.com/`
  - ✅ No authentication
  - ✅ Random cat images
  - Endpoint: `/images/cataas/random`

---

## ⚠️ APIs Requiring Authentication

### Images & Photos
- **Unsplash API** - `https://api.unsplash.com/`
  - ⚠️ **Requires OAuth2 token**
  - Free tier: 50 requests/hour
  - Register at: https://unsplash.com/developers
  - Endpoint: `/images/unsplash/random`
  - Status: Operational (verified 2026-04-01)

---

## ❌ Currently Unavailable APIs

### E-commerce
- **Fake Store API** - `https://fakestoreapi.com/`
  - ❌ **DOWN** - 523 Error (Origin unreachable)
  - Last checked: 2026-04-01 14:33:09 UTC
  - **Use Alternative:** Platzi Fake Store API or DummyJSON
  - Endpoint affected: `/ecommerce/products`

### Science & Space
- **Open Notify ISS API** - `https://api.open-notify.org/`
  - ⏱️ **TIMEOUT** - Connection issues
  - **Use Alternative:** SpaceX API for space data
  - Endpoint affected: `/science/iss/position`

---

## 🔄 Recommended Alternatives

### For E-commerce (Instead of Fake Store API):
1. **DummyJSON Products**
   - URL: `https://dummyjson.com/products`
   - ✅ Fully operational
   - 100 products with images

2. **Platzi Fake Store API** (NEW)
   - URL: `https://api.escuelajs.co/api/v1/products`
   - ✅ Fully operational
   - Modern API with categories

### For ISS Tracking:
- Use **SpaceX API** for space-related data
- URL: `https://api.spacexdata.com/v4/launches/latest`

---

## 📊 Summary Statistics

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Fully Operational | 13 | 76.5% |
| ⚠️ Auth Required | 1 | 5.9% |
| ❌ Down/Issues | 2 | 11.8% |
| **Total Tested** | **17** | **100%** |

---

## 🔧 How to Use This Data

### For LLMs:
1. Check the status before calling any API
2. Prefer APIs marked with ✅
3. Have fallback options ready for ⚠️ and ❌ APIs
4. Use direct_url from category JSON files

### For Developers:
1. All operational APIs return valid JSON
2. Sample responses in JSON files are accurate
3. Update your code to use alternatives for down APIs
4. Consider implementing retry logic

---

## 📝 Testing Methodology

- **Tool:** Chrome DevTools MCP
- **Browser:** Chrome with remote debugging
- **Method:** Direct API calls via browser
- **Verification:** Snapshot-based response capture
- **Success Criteria:** Valid JSON with expected structure

---

## 🔄 Maintenance Schedule

**Recommended:** Re-verify APIs monthly

**Automated Testing:**
```bash
# Run verification script
python verify_test_responses.py

# Check specific category
pytest tests/test_weather.py -v
```

---

## 📚 Related Documentation

- [API Verification Report](./API_VERIFICATION_REPORT.md) - Detailed test results
- [API Catalog](./api_catalog_with_responses.json) - Full API catalog with responses
- [Category Index](./categories/index.json) - Navigate all categories
- [LLM Integration Guide](./LLM_INTEGRATION.md) - How to use APIs in LLM applications

---

## ⚡ Quick Start Examples

### Weather
```bash
curl "https://api.open-meteo.com/v1/forecast?latitude=40.71&longitude=-74.01&current_weather=true"
```

### Currency Exchange
```bash
curl "https://api.frankfurter.app/latest?from=USD&to=EUR"
```

### Random Joke
```bash
curl "https://v2.jokeapi.dev/joke/Any?safe-mode"
```

### Dictionary
```bash
curl "https://api.dictionaryapi.dev/api/v2/entries/en/hello"
```

### Products (Use DummyJSON instead of Fake Store)
```bash
curl "https://dummyjson.com/products?limit=10"
```

---

**Note:** This document is auto-generated based on live API testing. Last update: 2026-04-01.
