FROM python:3.12-slim

# 1. Install uv directly from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. Set the working directory first
WORKDIR /app

# 3. Copy only the dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# 4. Sync dependencies
# Using --frozen ensures it strictly follows uv.lock
RUN uv sync --frozen

# 5. Copy the rest of your application code
COPY . .

# 6. Expose the port (optional but good practice for documentation)
EXPOSE 8000

# 7. Use 'uv run' to execute uvicorn within the virtual environment created by 'uv sync'
# Also using the recommended JSON array syntax for CMD
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]