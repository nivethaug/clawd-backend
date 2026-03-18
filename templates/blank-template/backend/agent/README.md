# Agent Module Guide

This folder contains AI-powered agents and dynamic endpoint generation.

---

## 📁 Structure

```
agent/
├ ai_index/
│   ├ index_creation_guide.md   # How to create AI indexes for codebases
│   ├ modules.json              # Generated: Module groupings
│   ├ symbols.json              # Generated: Functions, classes, APIs
│   ├ dependencies.json         # Generated: File relationships
│   ├ summaries.json            # Generated: Semantic summaries
│   └ files.json                # Generated: File metadata
├ endpoints/                    # Dynamic endpoint definitions
│   └ *.yaml                    # Endpoint specifications
└ README.md                     # This file
```

---

## 🔧 How to Add a New Endpoint

### Option 1: Standard Route (Recommended)

1. Create a new route file in `routes/`:

```python
# routes/products.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db

router = APIRouter(prefix="/api/products", tags=["Products"])

@router.get("/")
async def list_products(db: Session = Depends(get_db)):
    """List all products."""
    return {"products": []}

@router.post("/")
async def create_product(db: Session = Depends(get_db)):
    """Create a new product."""
    return {"id": 1}
```

2. Register in `main.py`:

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
