-- Project Ports Database Schema

-- Stores allocated ports for projects to avoid conflicts
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    frontend_port INTEGER,
    backend_port INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for port lookups
CREATE INDEX IF NOT EXISTS idx_frontend_port ON projects(frontend_port);
CREATE INDEX IF NOT EXISTS idx_backend_port ON projects(backend_port);
