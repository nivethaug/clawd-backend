# Agent Guide - Backend Code Navigation & Modification

This folder helps AI assistants understand and modify the codebase efficiently.

## AI Index Files

| File | Purpose | When to Update |
|------|---------|----------------|
| `ai_index/symbols.json` | Functions, classes, APIs with line numbers | After adding/editing/removing any code |
| `ai_index/modules.json` | Logical module groupings | After adding new files/modules |
| `ai_index/dependencies.json` | Import relationships between files | After changing imports |
| `ai_index/summaries.json` | Semantic descriptions per file | After significant file changes |
| `ai_index/files.json` | File metadata (lines, endpoints) | After adding/removing files |

---

## How to Add New Endpoint

### 1. Read existing pattern
```
Read: ai_index/symbols.json → Find similar endpoint (e.g., "login", "register")
```

### 2. Create route file (if new module) or add to existing
```python
# routes/products.py
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/products", tags=["products"])

class ProductCreate(BaseModel):
    name: str
    price: float

@router.post("/")
async def create_product(data: ProductCreate):
    # Implementation
    return {"id": 1, "name": data.name}
```

### 3. Register router in main.py
```python
from routes.products import router as products_router
app.include_router(products_router)
```

### 4. Update AI Index
Add to `ai_index/symbols.json`:
```json
"create_product": {
  "type": "api",
  "file": "routes/products.py",
  "start_line": 12,
  "end_line": 16,
  "module": "routes",
  "description": "POST /api/products - Create new product"
}
```

---

## How to Edit Existing Endpoint

### 1. Find the endpoint
```
Read: ai_index/symbols.json → Search for endpoint name
```

### 2. Navigate to file and lines
```
symbols.json gives you: file path + start_line + end_line
```

### 3. Make changes

### 4. Update AI Index
Update line numbers in `ai_index/symbols.json` if they changed.

---

## How to Remove Endpoint

### 1. Find the endpoint in `ai_index/symbols.json`

### 2. Delete the code from the route file

### 3. Remove router from `main.py` if entire file removed

### 4. Update AI Index
- Remove entry from `ai_index/symbols.json`
- Remove from `ai_index/files.json` if file deleted
- Update `ai_index/dependencies.json` if imports changed

---

## Quick Reference: AI Index Update Checklist

| Action | symbols | modules | dependencies | summaries | files |
|--------|:-------:|:-------:|:------------:|:---------:|:-----:|
| Add endpoint | ✅ | - | - | - | - |
| Edit endpoint | ✅ | - | - | - | - |
| Remove endpoint | ✅ | - | - | - | - |
| Add new file | ✅ | ✅ | ✅ | ✅ | ✅ |
| Delete file | ✅ | ✅ | ✅ | ✅ | ✅ |
| Change imports | - | - | ✅ | - | - |

---

## Endpoints Folder

`endpoints/` contains YAML definitions for planned/implemented endpoints:

```yaml
# endpoints/products.yaml
path: /api/products
methods:
  GET:
    description: List all products
    auth: required
  POST:
    description: Create product
    body: {name: string, price: number}
```

Use this to plan endpoints before implementation.

```python
from routes.products import router as products_router
app.include_router(products_router)
```

### Option 2: Agent-Generated Endpoint

1. Create an endpoint definition in `agent/endpoints/`:

```yaml
# agent/endpoints/products.yaml
name: products
prefix: /api/products
endpoints:
  - method: GET
    path: /
    description: List all products
    response:
      products: list
  - method: POST
    path: /
    description: Create a new product
    body:
      name: string
      price: number
    response:
      id: number
      name: string
```

2. The agent will auto-generate the route file.

---

## ✏️ How to Change an Existing Endpoint

### Option 1: Direct Edit

1. Find the route file in `routes/`
2. Edit the endpoint function
3. Restart the service

### Option 2: Via AI Index

1. Update `ai_index/symbols.json` with new line numbers
2. Update `ai_index/summaries.json` with new description
3. The AI assistant uses these for context

---

## 🧠 AI Index Usage

The `ai_index/` folder helps AI assistants understand the codebase:

- **modules.json**: Logical grouping of files
- **symbols.json**: All functions, classes, APIs with locations
- **dependencies.json**: How files relate to each other
- **summaries.json**: Semantic descriptions

### Generating AI Index

Run the indexing script:

```bash
python -m agent.indexer
```

Or use the AI to analyze and generate manually.

---

## 📝 Best Practices

1. **One route file per domain** (auth, products, users, etc.)
2. **Use dependency injection** for database sessions
3. **Add docstrings** for AI indexing
4. **Keep endpoints RESTful**
5. **Update AI index** after major changes

---

## 🔄 Workflow

```
1. Define endpoint in routes/
2. Add models in models/ (if needed)
3. Add business logic in services/ (if complex)
4. Register router in main.py
5. Update AI index
6. Test and deploy
```
