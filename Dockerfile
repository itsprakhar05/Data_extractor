FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Create venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install build deps then cleanup
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
  && if [ -s /app/requirements.txt ]; then pip install -r /app/requirements.txt; fi

# Copy project files (frontend excluded via .dockerignore)
COPY . /app

ENV CONFIG_PATH=/app/config/config.json
EXPOSE 8000 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]