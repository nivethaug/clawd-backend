# Agent Guide - Backend Code Navigation & Modification

This folder helps AI assistants understand and modify the codebase efficiently.

---

## 🚀 PM2 Process Management (CRITICAL)

### Process Information

| Property | Value |
|----------|-------|
| **PM2 Process Name** | `{domain}-backend` |
| **Domain** | `{domain}.dreambigwithai.com` |
| **API Domain** | `{domain}-api.dreambigwithai.com` |
| **PM2 Config File** | `ecosystem.config.json` |
| **Entry Point** | `main:app` (uvicorn ASGI) |
| **Default Port** | `8010` |

### How to Publish Backend

From the `backend/` directory:

```bash
# Install deps only (no restart)
python3 buildpublish.py

# Install deps + restart PM2 + reload nginx
python3 buildpublish.py --restart
```

**Options:**

| Flag | Description |
|------|-------------|
| `--skip-deps` | Skip pip install |
| `--skip-migrations` | Skip database migrations |
| `--restart` | Restart PM2 and nginx |

### Manual PM2 Commands

```bash
pm2 status                          # Check status
pm2 logs {domain}-backend           # View logs
pm2 restart {domain}-backend        # Restart service
pm2 stop {domain}-backend           # Stop service
pm2 save                            # Persist across reboot
```

---

## 🚀 How to Publish Backend

### Quick Publish (Recommended)

From the `backend/` directory, run:

```bash
python3 buildpublish.py
```

This single command:
1. Installs Python dependencies (using shared venv)
2. Verifies main.py exists
3. Runs database migrations (if alembic.ini exists)

### With PM2 Restart

To restart the service after publishing:

```bash
python3 buildpublish.py --restart --domain {domain}
# Example: python3 buildpublish.py --restart --domain myapp-abc123
# Restarts myapp-abc123-backend PM2 process
```

### Output Example

```
==================================================
PIP INSTALL
==================================================
📦 Using shared venv: /root/dreampilot/dreampilotvenv
✓ pip install --prefer-binary -r requirements.txt

==================================================
✓ main.py verified: 1234 bytes

==================================================
DATABASE MIGRATIONS
==================================================
⚠ No alembic.ini found, skipping migrations

==================================================
✓ BUILD & PUBLISH COMPLETE
==================================================
```

### Options

| Flag | Description |
|------|-------------|
| `--skip-deps` | Skip pip install |
| `--skip-migrations` | Skip database migrations |
| `--restart` | Restart PM2 and nginx (requires --domain) |
| `--domain` | Domain for PM2 app name (e.g., myapp-abc123) |
| `--venv` | Custom virtual environment path |

### When to Use

| Scenario | Command |
|----------|---------|
| After code changes | `python3 buildpublish.py --restart --domain {domain}` |
| Just install deps | `python3 buildpublish.py --skip-migrations` |
| Run migrations only | `python3 buildpublish.py --skip-deps` |
| Custom venv | `python3 buildpublish.py --venv /path/to/venv` |

---

## �🗄️ Database Connection Details (CRITICAL)

### How Backend Connects to Database

The backend uses **SQLAlchemy ORM** with a connection string from environment variables:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  PM2 Ecosystem  │────▶│  Environment     │────▶│  SQLAlchemy     │
│  Config JSON    │     │  Variables       │     │  Engine         │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                                 ┌─────────────────┐
                                                 │  PostgreSQL     │
                                                 │  Database       │
                                                 └─────────────────┘
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Full PostgreSQL connection string | `postgresql://{user}:{pass}@{host}:5432/{db}` |
| `PORT` | Backend API port | `8010` |
| `PROJECT_NAME` | Project identifier | `MyProject` |
| `HOST` | Bind address | `0.0.0.0` |

### Database Configuration Files

| File | Purpose |
|------|---------|
| `core/config.py` | Reads `DATABASE_URL` from environment |
| `core/database.py` | SQLAlchemy engine, session factory, `Base` class |
| `models/*.py` | SQLAlchemy model definitions (tables) |

### Database Naming Convention

```
Project: "MyProject"
├── Database: myproject_db (lowercase, hyphens → underscores)
├── Username: myproject_user
└── Password: 32-char alphanumeric (no special chars)
```

**⚠️ Important:** All database identifiers are lowercase to avoid PostgreSQL case-sensitivity issues.

### DATABASE_URL Format

```
postgresql://{username}:{password}@{host}:{port}/{database}
```

| Component | Source |
|-----------|--------|
| `username` | `{project_name}_user` (lowercase) |
| `password` | 32-char alphanumeric |
| `host` | `postgres` (Docker) or `localhost` |
| `port` | `5432` |
| `database` | `{project_name}_db` (lowercase) |

---

## 🤖 Agent Guide: Database Modifications

### How to Read Current Database Schema

**Option 1: Read Models**
```python
# Check models/ folder for all table definitions
# Each model class = one database table
```

**Option 2: Query Database Directly**
```python
from core.database import engine
from sqlalchemy import inspect, text

inspector = inspect(engine)

# List all tables
tables = inspector.get_table_names()
print(f"Tables: {tables}")

# Get columns for a table
columns = inspector.get_columns('users')
for col in columns:
    print(f"  {col['name']}: {col['type']}")
```

**Option 3: Check ai_index/database_schema.json**
```json
{
  "tables": {
    "users": {
      "columns": {"id": "Integer", "email": "String", ...},
      "relationships": [...]
    }
  }
}
```

### How to Add a New Table

**Step 1: Create Model File**

```python
# models/product.py
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from core.database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
```

**Step 2: Import in models/__init__.py**

```python
from models.user import User
from models.product import Product  # Add this

__all__ = ["User", "Product"]
```

**Step 3: Register in core/database.py**

```python
# Ensure model is imported so Base.metadata.create_all() creates the table
import models.product  # Add this
```

**Step 4: Tables Auto-Create on Startup**

The `init_db()` function in `core/database.py` creates all tables:
```python
Base.metadata.create_all(bind=engine)
```

### How to Add a New Column to Existing Table

**Step 1: Update Model**

```python
# models/user.py
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    phone = Column(String(20))  # ← NEW COLUMN
    created_at = Column(DateTime, server_default=func.now())
```

**Step 2: Restart Backend**

SQLAlchemy will NOT automatically add columns. Use Alembic migration:

```bash
# Create migration
alembic revision --autogenerate -m "Add phone column to users"

# Apply migration
alembic upgrade head
```

**Or Manual SQL (Quick Fix):**
```python
from core.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(20)"))
    conn.commit()
```

### How to Create a New Relationship

**Step 1: Add Foreign Key**

```python
# models/order.py
from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))  # FK
    total = Column(Float)
    
    # Relationship
    user = relationship("User", back_populates="orders")
```

**Step 2: Add Back-Reference**

```python
# models/user.py
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True)
    
    # Back-reference
    orders = relationship("Order", back_populates="user")
```

### How to Query the Database

```python
from sqlalchemy.orm import Session
from core.database import SessionLocal
from models.user import User

# Get database session
db: Session = SessionLocal()

# Create
new_user = User(email="test@example.com", password="hashed")
db.add(new_user)
db.commit()
db.refresh(new_user)

# Read
user = db.query(User).filter(User.email == "test@example.com").first()
users = db.query(User).all()

# Update
user.password = "new_hashed"
db.commit()

# Delete
db.delete(user)
db.commit()

# Always close
db.close()
```

### Database Modification Checklist

| Action | Update Model | Migration | Restart | Update ai_index |
|--------|:------------:|:---------:|:-------:|:---------------:|
| Add table | ✅ | Auto | ✅ | ✅ |
| Add column | ✅ | ✅ | ✅ | ✅ |
| Remove column | ✅ | ✅ | ✅ | ✅ |
| Add relationship | ✅ | ✅ | ✅ | ✅ |
| Change column type | ✅ | ✅ | ✅ | ✅ |

---

## Common Database Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `password authentication failed` | Wrong credentials | Check DATABASE_URL in ecosystem.config.json |
| `database "X" does not exist` | DB not created | Check infrastructure logs |
| `permission denied for schema public` | PG 15+ permissions | Run schema GRANT commands |
| `relation "X" does not exist` | Table not created | Check model imported, restart backend |
| `column "X" does not exist` | Migration not applied | Run Alembic migration or manual ALTER |

---

## PostgreSQL Schema Permissions (PG 15+)

PostgreSQL 15+ requires explicit schema permissions:

```sql
GRANT ALL ON SCHEMA public TO "{project_user}";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{project_user}";
```

---

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
