# Public API Catalog for LLMs & Telegram Bots

> **Last Updated:** 2025-03-31 | **Version:** 1.0.0 | **Total APIs:** 35 | **Total Endpoints:** 100

## Quick Reference Matrix

| User Intent | API Provider | Endpoint | Auth Required |
|-------------|--------------|----------|---------------|
| "bitcoin price" | CoinGecko | `/finance/crypto/coingecko/coins` | ❌ No |
| "weather forecast" | Open-Meteo | `/weather/open-meteo` | ❌ No |
| "tell me a joke" | JokeAPI | `/entertainment/jokes/random` | ❌ No |
| "translate text" | MyMemory | `/ai/translate` | ❌ No |
| "news headlines" | HackerNews | `/news/hackernews/top` | ❌ No |
| "movie info" | TMDB | `/entertainment/movies/tmdb/popular` | ✅ API Key |
| "recipe ideas" | TheMealDB | `/food/meals/search` | ❌ No |
| "currency convert" | Frankfurter | `/currency/convert` | ❌ No |
| "random quote" | Quotable | `/entertainment/quotes/random` | ❌ No |
| "dog picture" | Dog CEO | `/images/dogceo/random` | ❌ No |

---

## Category 1: Cryptocurrency & Finance

### CoinGecko (Recommended for crypto prices)
- **Direct URL:** `https://api.coingecko.com/api/v3`
- **Auth:** None required
- **Rate Limit:** 10-50 calls/min (varies)

#### Endpoints:

**List Cryptocurrencies**
```
GET https://api.coingecko.com/api/v3/coins/markets
Parameters:
  - vs_currency: usd, eur, btc (default: usd)
  - per_page: 1-250 (default: 50)
  - page: page number (default: 1)
```

**Get Single Coin**
```
GET https://api.coingecko.com/api/v3/coins/{coin_id}
Parameters:
  - coin_id: bitcoin, ethereum, dogecoin, etc.
```

### CoinCap
- **Direct URL:** `https://api.coincap.io/v2`
- **Auth:** None required

**List Assets**
```
GET https://api.coincap.io/v2/assets
Parameters:
  - limit: 1-2000 (default: 50)
  - search: filter by name/symbol
```

### Binance
- **Direct URL:** `https://api.binance.com/api/v3`
- **Auth:** None required

**24hr Ticker**
```
GET https://api.binance.com/api/v3/ticker/24hr
Parameters:
  - symbol: BTCUSDT, ETHUSDT, etc.
```

### Exchange Rates
```
GET https://api.exchangerate-api.com/v4/latest/{base}
Example: https://api.exchangerate-api.com/v4/latest/USD
```

---

## Category 2: Weather

### Open-Meteo (Recommended)
- **Direct URL:** `https://api.open-meteo.com/v1`
- **Auth:** None required
- **No rate limit**

**Current Weather & Forecast**
```
GET https://api.open-meteo.com/v1/forecast
Parameters:
  - latitude: decimal degrees
  - longitude: decimal degrees
  - current_weather: true/false
  - hourly: temperature_2m,precipitation
  - daily: temperature_2m_max,temperature_2m_min
```

### US National Weather Service
```
GET https://api.weather.gov/alerts
Parameters:
  - active: 1 (for active alerts)
  - area: US state code (e.g., CA, NY)
```

---

## Category 3: News & Content

### HackerNews
- **Direct URL:** `https://hacker-news.firebaseio.com/v0`
- **Auth:** None required

**Top Stories**
```
GET https://hacker-news.firebaseio.com/v0/topstories.json
Returns: Array of story IDs [12345, 12346, ...]
```

**Story Details**
```
GET https://hacker-news.firebaseio.com/v0/item/{story_id}.json
```

---

## Category 4: Entertainment

### Jokes
```
GET https://v2.jokeapi.dev/joke/Any
Returns: Single or two-part joke

GET https://api.chucknorris.io/jokes/random
Returns: Chuck Norris joke
```

### Quotes
```
GET https://api.quotable.io/random
Returns: Inspirational quote with author
```

### Fun Facts
```
GET https://uselessfacts.jsph.pl/random.json?language=en
Returns: Random trivia fact
```

### Movies (Requires API Key)
```
GET https://api.themoviedb.org/3/movie/popular
Headers: Authorization: Bearer {api_key}
Get free key: https://www.themoviedb.org/settings/api
```

---

## Category 5: AI & NLP

### Translation (MyMemory)
```
GET https://api.mymemory.translated.net/get
Parameters:
  - q: text to translate
  - langpair: en|es, en|fr, etc.
Example: ?q=Hello&langpair=en|es
```

### Random User Generator (Testing)
```
GET https://randomuser.me/api/
Returns: Fake user profile data
```

---

## Category 6: Location & Geography

### Countries
```
GET https://restcountries.com/v3.1/all
GET https://restcountries.com/v3.1/alpha/{code}
Returns: Country info (population, capital, flag, etc.)
```

### Geocoding
```
GET https://nominatim.openstreetmap.org/reverse
Parameters:
  - lat: latitude
  - lon: longitude
  - format: json
Returns: Address from coordinates
```

### IP Location
```
GET http://ip-api.com/json/{ip}
Returns: City, country, ISP from IP address
```

---

## Category 7: Food & Recipes

### Meals
```
GET https://www.themealdb.com/api/json/v1/1/search.php
Parameters:
  - s: search by name
  - i: search by ingredient
  
GET https://www.themealdb.com/api/json/v1/1/random.php
Returns: Random recipe
```

### Cocktails
```
GET https://www.thecocktaildb.com/api/json/v1/1/search.php?s={name}
GET https://www.thecocktaildb.com/api/json/v1/1/random.php
```

### Breweries
```
GET https://api.openbrewerydb.org/breweries
Parameters:
  - by_city: city name
  - by_state: state name
  - per_page: 1-50
```

---

## Category 8: Images

### Random Dogs
```
GET https://dog.ceo/api/breeds/image/random
Returns: { "message": "image_url", "status": "success" }
```

### Random Cats
```
GET https://cataas.com/cat?json=true
Returns: Cat image URL
```

### Placeholder Images
```
GET https://picsum.photos/{width}/{height}
Example: https://picsum.photos/800/600
```

### Stock Photos (Requires API Key)
```
GET https://api.unsplash.com/photos/random
Headers: Authorization: Client-ID {access_key}
```

---

## Category 9: Sports

### NBA
```
GET https://www.balldontlie.io/api/v1/players
GET https://www.balldontlie.io/api/v1/teams
No auth required
```

### Formula 1
```
GET https://ergast.com/api/f1/current/driverStandings.json
Returns: Current season driver standings
```

### Football (Requires API Key)
```
GET https://api.football-data.org/v4/matches
Headers: X-Auth-Token: {api_key}
```

---

## Category 10: Utilities

### QR Code Generation
```
GET https://api.qrserver.com/v1/create-qr-code/
Parameters:
  - size: 200x200
  - data: text/URL to encode
```

### Color Information
```
GET https://www.thecolorapi.com/id
Parameters:
  - hex: color code without # (e.g., 00FF00)
Returns: Color name, RGB, HSL values
```

### UUID Generation (Local)
```python
import uuid
str(uuid.uuid4())  # Returns: "550e8400-e29b-41d4-a716-446655440000"
```

### Text Hashing (Local)
```python
import hashlib
hashlib.sha256("text".encode()).hexdigest()
```

---

## Authentication Requirements Summary

### No Authentication Required (91% of APIs)
- All cryptocurrency APIs (CoinGecko, CoinCap, Binance, Coinbase)
- All weather APIs (Open-Meteo, 7Timer, NWS)
- All entertainment APIs except TMDB
- All news, location, food, utility APIs

### API Key Required (9% of APIs)
| API | Key URL | Free Tier |
|-----|---------|-----------|
| TMDB (Movies) | https://www.themoviedb.org/settings/api | Yes |
| Unsplash | https://unsplash.com/developers | Yes (50 req/hr) |
| Football-Data | http://api.football-data.org/client/register | Yes |

---

## Response Time Expectations

| API Type | Avg Response Time | Timeout Recommendation |
|----------|-------------------|------------------------|
| Local (UUID, Hash) | <1ms | 1s |
| Simple (Jokes, Quotes) | 50-200ms | 5s |
| Search (Coins, Recipes) | 200-500ms | 10s |
| Complex (Weather, Maps) | 500-1000ms | 15s |

---

## User Intent → API Mapping

### "How much is [crypto]?"
→ CoinGecko `/coins/markets` or `/coins/{coin_id}`

### "What's the weather in [location]?"
→ First geocode location, then Open-Meteo `/forecast`

### "Tell me something funny"
→ JokeAPI `/joke/Any` or Chuck Norris API

### "What's happening in tech?"
→ HackerNews `/topstories`

### "I want to cook something with [ingredient]"
→ TheMealDB `/search.php?s={ingredient}`

### "Convert [amount] [from] to [to]"
→ Frankfurter `/latest?from={from}&to={to}`

### "Show me a [dog/cat] picture"
→ Dog CEO or CATAAS API

### "What time is it in [city]?"
→ Geocode city, then TimezoneAPI

### "Give me a random [quote/fact]"
→ Quotable or Useless Facts API

### "Translate [text] to [language]"
→ MyMemory Translation API
