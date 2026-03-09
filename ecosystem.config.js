module.exports = {
  apps: [{
    name: 'clawd-backend',
    script: '/root/clawd-backend/app.py',
    interpreter: '/root/clawd-backend/venv/bin/python3',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    env: {
      EMPTY_TEMPLATE_MODE: 'true',
      DB_PATH: '/root/clawd-backend/clawdbot_adapter.db',
      USE_POSTGRES: 'true',
      DB_HOST: 'localhost',
      DB_PORT: '5432',
      DB_NAME: 'dreampilot',
      DB_USER: 'admin',
      DB_PASSWORD: 'StrongAdminPass123'
    }
  }]
};