"""
Simple Initializer

Creates backend, database, and environment files directly
without using Claude Code CLI. Much faster and more reliable.
"""

import sys
import logging
import sqlite3
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"


class SimpleInitializer:
    """Simple initializer that creates files directly."""

    def __init__(self, project_id: int, project_path: str, project_name: str):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
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
            logger.info(f"✓ Created: {backend_dir}")
            logger.info(f"✓ Created: {main_py}")
            logger.info(f"✓ Created: {requirements_txt}")
            logger.info(f"✓ Created: {env_example}")
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
            logger.info(f"✓ Created: {database_dir}")
            logger.info(f"✓ Created: {init_sql}")
            logger.info(f"✓ Created: {connection_py}")
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
            logger.info(f"✓ Created: {env_file}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to create environment file: {e}")
            return False

    def run_all(self):
        """Run all initialization tasks."""
        try:
            logger.info(f"🚀 Starting simple initialization for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")

            total_tasks = 3
            tasks_succeeded = 0

            # Task 1: Create backend
            logger.info(f"📋 Task 1/{total_tasks}: Create FastAPI backend")
            if self.create_backend():
                self.completed_tasks.append("Create backend")
                tasks_succeeded += 1
                logger.info(f"✓ Task 1 completed!")
            else:
                self.failed_tasks.append("Create backend")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 1")
                return

            # Task 2: Create database setup
            logger.info(f"📋 Task 2/{total_tasks}: Setup PostgreSQL")
            if self.create_database_setup():
                self.completed_tasks.append("Setup PostgreSQL")
                tasks_succeeded += 1
                logger.info(f"✓ Task 2 completed!")
            else:
                self.failed_tasks.append("Setup PostgreSQL")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Task 3: Create environment file
            logger.info(f"📋 Task 3/{total_tasks}: Configure environment")
            if self.create_environment():
                self.completed_tasks.append("Configure environment")
                tasks_succeeded += 1
                logger.info(f"✓ Task 3 completed!")
            else:
                self.failed_tasks.append("Configure environment")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 3")
                return

            # All tasks completed!
            if tasks_succeeded == 3:
                logger.info(f"✅ All {total_tasks} initialization tasks completed successfully!")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed tasks: {', '.join(self.completed_tasks)}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {tasks_succeeded}/{total_tasks}, Failed: {', '.join(self.failed_tasks)}")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error in simple initializer: {e}")
            self.update_status("failed")

        finally:
            logger.info("🏁 Simple initializer finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 simple_initializer.py <project_id> <project_path> <project_name>")
        print("  project_id: Database project ID")
        print("  project_path: Absolute path to project folder")
        print("  project_name: Project name")
        sys.exit(1)

    project_id = int(sys.argv[1])
    project_path = sys.argv[2]
    project_name = sys.argv[3]

    # Create and run initializer
    initializer = SimpleInitializer(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name
    )

    initializer.run_all()


if __name__ == "__main__":
    main()
