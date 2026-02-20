"""
Fast Wrapper for DreamPilot Project Initialization

Combines:
- Task 1: Template selection (Groq - fast)
- Task 2: Git clone (subprocess - fast)
- Tasks 3-5: Simple file creation (Python - fast)

No Claude Code CLI required! Everything is fast and reliable.
"""

import sys
import json
import subprocess
import logging
import sqlite3
from pathlib import Path

# Import fixed template lookup function
import template_lookup_fix

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"


class FastWrapper:
    """Fast wrapper using Groq, subprocess, and simple file creation."""

    def __init__(self, project_id: int, project_path: str, project_name: str, description: str = None, template_id: str = None):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.description = description or ""
        self.template_id = template_id
        self.completed_tasks = []
        self.failed_tasks = []

    def update_status(self, status: str):
        """Update project status in database."""
        try:
            logger.info(f"Updating project {self.project_id} status to '{status}'")
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(
                    "UPDATE projects SET status = ? WHERE id = ?",
                    (status, self.project_id)
                )
                conn.commit()
                logger.info(f"✓ Project {self.project_id} status updated to '{status}'")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"✗ Failed to update project status: {e}")

    def git_clone(self, repo_url: str, target_dir: str = "frontend", timeout: int = 600) -> bool:
        """Run git clone directly."""
        try:
            logger.info(f"🚀 Running git clone: {repo_url} → {target_dir}")

            # Check if target directory already exists
            target_path = self.project_path / target_dir
            if target_path.exists():
                logger.warning(f"⚠️ Target directory '{target_dir}' already exists, skipping clone")
                return True

            # Run git clone
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, target_dir],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Check result
            if result.returncode == 0:
                logger.info(f"✅ Git clone completed successfully")
                logger.info(f"✓ Repository cloned to {target_dir}")

                # Verify clone
                if target_path.exists():
                    logger.info(f"✓ Target directory verified: {target_dir}")
                    return True
                else:
                    logger.error(f"❌ Target directory not created: {target_dir}")
                    return False

            else:
                logger.error(f"❌ Git clone failed with code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Git clone timed out after {timeout} seconds")
            return False
        except Exception as e:
            logger.error(f"❌ Git clone error: {e}")
            return False

    def create_backend(self) -> bool:
        """Create FastAPI backend files."""
        try:
            logger.info("🚀 Creating FastAPI backend...")

            backend_dir = self.project_path / "backend"
            backend_dir.mkdir(exist_ok=True)

            # Create main.py
            main_py = backend_dir / "main.py"
            main_py.write_text("""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title=f"{os.getenv('PROJECT_NAME', 'API')} API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Hello World", "project": os.getenv('PROJECT_NAME', 'API')}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('BACKEND_PORT', os.getenv('API_PORT', '8000')))
    uvicorn.run(app, host="0.0.0.0", port=port)
""")

            # Create requirements.txt
            requirements_txt = backend_dir / "requirements.txt"
            requirements_txt.write_text("""fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pydantic==2.5.0
python-dotenv==1.0.0
psycopg2-binary==2.9.9
""")

            # Create .env.example
            env_example = backend_dir / ".env.example"
            env_example.write_text("""# Database
DATABASE_URL=postgresql://user:password@localhost/dbname

# API
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# Project
PROJECT_NAME=My API

# Security
SECRET_KEY=your-secret-key-here
""")

            logger.info("✅ Backend created successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to create backend: {e}")
            return False

    def create_database_setup(self) -> bool:
        """Create database setup files."""
        try:
            logger.info("🚀 Creating database setup...")

            database_dir = self.project_path / "database"
            database_dir.mkdir(exist_ok=True)

            # Create init.sql
            init_sql = database_dir / "init.sql"
            init_sql.write_text("""-- Initialize database schema

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at);
""")

            # Create connection.py
            connection_py = database_dir / "connection.py"
            connection_py.write_text("""from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/dbname')

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Models
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
""")

            logger.info("✅ Database setup created successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to create database setup: {e}")
            return False

    def create_environment(self) -> bool:
        """Create environment file."""
        try:
            logger.info("🚀 Creating environment file...")

            # Create .env file
            env_file = self.project_path / ".env"
            env_file.write_text(f"""# Database
DATABASE_URL=postgresql://user:password@localhost/dbname

# API
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# Project
PROJECT_NAME={self.project_name}

# Security
SECRET_KEY=your-secret-key-here-generate-new-one-in-production
""")

            logger.info("✅ Environment file created successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to create environment file: {e}")
            return False

    def run(self):
        """Run all 5 initialization steps."""
        try:
            logger.info(f"🚀 Starting fast initialization for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")

            tasks_succeeded = 0
            total_tasks = 5

            # Task 1: Select template from registry (SKIP if template_id is provided)
            if self.template_id:
                logger.info(f"📋 Task 1/{total_tasks}: Select template from registry - SKIPPED (template_id provided: {self.template_id})")
                self.completed_tasks.append("Select template")
                tasks_succeeded += 1
                logger.info(f"✓ Task 1 skipped - using pre-selected template: {self.template_id}")
            else:
                logger.info(f"📋 Task 1/{total_tasks}: Select template from registry - SKIPPED (use Groq API before calling wrapper)")
                self.completed_tasks.append("Select template")
                tasks_succeeded += 1
                logger.info(f"✓ Task 1 skipped - template should be selected via Groq API")

            # Task 2: Clone repository
            logger.info(f"📋 Task 2/{total_tasks}: Clone repository")

            # Get template repository URL
            template_registry_path = Path("/root/dreampilot/website/frontend/template-registry.json")
            repo_url = None

            if self.template_id:
                logger.info(f"Looking up template ID: {self.template_id}")

                try:
                    with open(template_registry_path, 'r') as f:
                        registry = json.load(f)
                        logger.info(f"Registry loaded successfully, {len(registry.get('templates', []))} templates available")
                except Exception as e:
                    logger.error(f"Failed to read template registry: {e}")
                    return None

                # Search for template
                if registry:
                    templates = registry.get('templates', [])
                    logger.info(f"Searching through templates for ID: '{self.template_id}'")
                    
                    for i, template in enumerate(templates):
                        template_id_check = template.get('id')
                        logger.info(f"  Template {i}: ID='{template_id_check}' (comparing to '{self.template_id}')")
                        
                        if template_id_check == self.template_id:
                            repo_url = template.get('repo')
                            logger.info(f"✓ MATCH FOUND! Template ID '{self.template_id}' matches at index {i}")
                            logger.info(f"✓ Repository URL: {repo_url}")
                            logger.info(f"✓ Template Category: {template.get('category')}")
                            break
                    else:
                        logger.error("No templates found in registry (registry is None)")

            if not repo_url:
                logger.error(f"❌ Could not find repository URL for template ID: {self.template_id}")
                logger.error(f"❌ Template registry path: {template_registry_path}")
                logger.error(f"❌ Template ID provided: '{self.template_id}'")
                self.failed_tasks.append("Clone repository")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Clone repository directly with subprocess (much faster than Claude Code)
            if self.git_clone(repo_url, "frontend", timeout=1800):
                self.completed_tasks.append("Clone repository")
                tasks_succeeded += 1
                logger.info(f"✓ Task 2 completed!")
            else:
                self.failed_tasks.append("Clone repository")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Task 3: Create FastAPI backend
            logger.info(f"📋 Task 3/{total_tasks}: Create FastAPI backend")
            if self.create_backend():
                self.completed_tasks.append("Create backend")
                tasks_succeeded += 1
                logger.info(f"✓ Task 3 completed!")
            else:
                self.failed_tasks.append("Create backend")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 3")
                return

            # Task 4: Setup PostgreSQL
            logger.info(f"📋 Task 4/{total_tasks}: Setup PostgreSQL")
            if self.create_database_setup():
                self.completed_tasks.append("Setup PostgreSQL")
                tasks_succeeded += 1
                logger.info(f"✓ Task 4 completed!")
            else:
                self.failed_tasks.append("Setup PostgreSQL")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 4")
                return

            # Task 5: Configure environment
            logger.info(f"📋 Task 5/{total_tasks}: Configure environment")
            if self.create_environment():
                self.completed_tasks.append("Configure environment")
                tasks_succeeded += 1
                logger.info(f"✓ Task 5 completed!")
            else:
                self.failed_tasks.append("Configure environment")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 5")
                return

            # All tasks completed!
            if tasks_succeeded == 5:
                logger.info(f"✅ All {total_tasks} initialization tasks completed successfully!")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed tasks: {', '.join(self.completed_tasks)}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {tasks_succeeded}/{total_tasks}, Failed: {', '.join(self.failed_tasks)}")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error in fast wrapper: {e}")
            self.update_status("failed")

        finally:
            logger.info("🏁 Fast wrapper finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 fast_wrapper.py <project_id> <project_path> <project_name> [description] [template_id]")
        print("  project_id: Database project ID")
        print("  project_path: Absolute path to project folder")
        print("  project_name: Project name")
        print("  description: (optional) Project description")
        print("  template_id: (optional) Pre-selected template ID")
        sys.exit(1)

    project_id = int(sys.argv[1])
    project_path = sys.argv[2]
    project_name = sys.argv[3]
    description = sys.argv[4] if len(sys.argv) > 4 else None
    template_id = sys.argv[5] if len(sys.argv) > 5 else None

    # Create and run wrapper
    wrapper = FastWrapper(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name,
        description=description,
        template_id=template_id
    )

    wrapper.run()


if __name__ == "__main__":
    main()
