FROM python:3.11-slim

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml .
RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy jinja2 aiofiles python-multipart

# Copy app code
COPY . .

EXPOSE $PORT

CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT