module.exports = {
  apps: [
    {
      name: 'clawd-backend',
      script: './venv/bin/uvicorn',
      args: 'app:app --host 0.0.0.0 --port 8002',
      cwd: '/root/clawd-backend',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production',
        USE_POSTGRES: 'true',
        DB_HOST: 'localhost',
        DB_PORT: '5432',
        DB_NAME: 'dreampilot',
        DB_USER: 'admin',
        DB_PASSWORD: 'YOUR_DB_PASSWORD_HERE',
        HOSTINGER_API_TOKEN: 'YOUR_HOSTINGER_API_TOKEN_HERE',
        GROQ_API_KEY: 'YOUR_GROQ_API_KEY_HERE'
      },
      error_file: './logs/backend-error.log',
      out_file: './logs/backend-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      max_restarts: 10,
      min_uptime: '10s',
      kill_timeout: 5000,
      wait_ready: true,
      listen_timeout: 10000
    }
  ]
};
