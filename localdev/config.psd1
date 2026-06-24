@{
  project  = 'uc_nexus'
  database = @{ engine = 'postgres' }

  secrets = @(
    @{ key = 'CLERK_SECRET_KEY';           file = 'backend/.env';        prompt = 'sk_test_...' }
    @{ key = 'VITE_CLERK_PUBLISHABLE_KEY'; file = 'frontend/.env.local'; prompt = 'pk_test_...' }
    @{ key = 'BUCKET_ENDPOINT';            file = 'backend/.env' }
    @{ key = 'BUCKET_ACCESS_KEY_ID';       file = 'backend/.env' }
    @{ key = 'BUCKET_SECRET_ACCESS_KEY';   file = 'backend/.env' }
    @{ key = 'BUCKET_NAME';                file = 'backend/.env' }
  )

  env = @(
    @{ file = 'backend/.env'; line = 'DATABASE_URL={DB_URL}' }
    @{ file = 'backend/.env'; line = 'TESTING_ENABLED=true' }
  )

  services = @(
    @{ name = 'backend';  dir = 'backend';  install = 'poetry install'; migrate = 'poetry run alembic upgrade head'; run = 'poetry run uvicorn main:app --reload --port {PORT}'; basePort = 8000; dbUrlEnv = 'DATABASE_URL' }
    @{ name = 'frontend'; dir = 'frontend'; install = 'npm ci'; run = 'npm run dev'; basePort = 5173; env = @{ UC_BACKEND_PORT = '{port:backend}'; UC_FRONTEND_PORT = '{PORT}' } }
  )
}
