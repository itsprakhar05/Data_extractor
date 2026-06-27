# Project File Structure

This document describes the current directory and file layout for the repository.

```
open_project/
├── .dockerignore
├── .dvc/
├── .dvcignore
├── .env
├── .git/
├── .gitignore
├── .venv/
├── app/
│   ├── pipeline.py
│   └── api/
│       └── routes/
│           ├── delete.py
│           ├── ingest.py
│           └── query.py
├── auth_server.py
├── build.log
├── config/
│   └── config.json
├── data/
│   ├── embedded_chunks/
│   │   ├── Input2_embedded.json
│   │   ├── PSfile_embedded.json
│   │   ├── input1.pdf_embedded.json
│   │   ├── input1_embedded.json
│   │   ├── sample_embedded.json
│   │   └── input1.pdf_embedded.json
│   ├── json_chunks/
│   │   ├── Input2_chunks.json
│   │   ├── PSfile_chunks.json
│   │   ├── input1.pdf_chunks.json
│   │   ├── input1_chunks.json
│   │   └── sample_chunks.json
│   ├── metrics/
│   │   └── ingest_metrics.json
│   ├── temp_extraction/
│   │   ├── Input2.md
│   │   ├── PSfile.md
│   │   ├── input1.md
│   │   ├── input1.pdf.md
│   │   ├── sample.md
│   │   ├── Input2_images/
│   │   ├── PSfile_images/
│   │   ├── input1.pdf_images/
│   │   ├── input1_images/
│   │   └── sample_images/
│   └── uploads/
├── Dockerfile
├── dvc.lock
├── dvc.yaml
├── frontend/
│   └── index.html
├── main.py
├── mlops_tool_demo/
│   ├── demo.py
│   └── requirements.txt
├── Modelfile
├── models/
│   └── query.py
├── pipeline_run.py
├── README.md
└── requirements.txt
```

> Note: Hidden directories such as `.git`, `.dvc`, and the virtual environment `.venv` are included for completeness.
