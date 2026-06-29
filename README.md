# Data Extractor

A lightweight document ingestion and retrieval system built with FastAPI, Apache Solr, and a Groq-powered RAG pipeline. It allows users to upload PDF documents, extract and chunk their contents, store them in Solr for semantic search, and ask questions over the indexed knowledge base.

## Overview

This project combines:

- PDF ingestion and document processing
- Vector-based retrieval with Solr
- Query rewriting and semantic caching
- Streaming RAG responses using Groq
- Query logging and basic evaluation endpoints with RAGAS and MLflow
- A simple frontend for interacting with the system

## Features

- Upload PDF files through the API
- Automatically create searchable chunks from uploaded documents
- Query the knowledge base using natural language
- Stream answers token-by-token for a responsive experience
- Delete indexed documents by filename
- Track query history and evaluate responses

## Project Structure

- [main.py](main.py) — FastAPI app entry point
- [app/api/routes](app/api/routes) — REST endpoints for ingest, query, delete, and evaluation
- [app/pipeline](app/pipeline) — ingestion, retrieval, embedding, prompt building, and streaming logic
- [app/db](app/db) — SQLite-backed query logging
- [frontend](frontend) — simple web UI
- [config/config.json](config/config.json) — Solr and model configuration

## Prerequisites

- Python 3.11+
- Apache Solr running locally or remotely
- A Groq API key
- Optional: Docker for containerized deployment

## Environment Setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root with your Groq key:

   ```env
   GROQ_API_KEY=your_groq_api_key_here
   ```

4. Update the Solr URL and model settings in [config/config.json](config/config.json) if needed.

## Running the Application

Start the FastAPI server:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:

- http://localhost:8000/
- http://localhost:8000/docs for Swagger UI

## Main API Endpoints

### Ingest a PDF

- Method: POST
- Endpoint: /api/v1/ingest
- Form field: file

### Query the knowledge base

- Method: POST
- Endpoint: /api/v1/query
- Payload:

  ```json
  {
    "question": "What does this document contain?"
  }
  ```

### Delete indexed document chunks

- Method: DELETE
- Endpoint: /api/v1/delete
- Payload:

  ```json
  {
    "filename": "document.pdf"
  }
  ```

### Evaluation and query history

- GET /api/v1/queries
- GET /api/v1/queries/{query_id}
- POST /api/v1/evaluate/{query_id}
- POST /api/v1/evaluate/all

## Docker

Build and run the container:

```bash
docker build -t data-extractor .
docker run -p 8000:8000 --env-file .env data-extractor
```

## Notes

- The application expects Solr to be reachable at the URL configured in [config/config.json](config/config.json).
- Query logs are stored in a local SQLite database.
- If MLflow is available, evaluation results can be logged automatically.

## License

This project is intended for educational and demonstration purposes.
