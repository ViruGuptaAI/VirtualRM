FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server/ server/

# Copy env file if present (local dev only; Azure uses env vars from Container App)
COPY pass.env* ./

# Seed the CRM database at build time
RUN cd server && python seed_db.py

EXPOSE 8000

# Run from the server directory
WORKDIR /app/server
CMD ["python", "app.py"]
