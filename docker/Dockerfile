FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

# Install dependencies from pyproject.toml
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" "pydantic>=2.10.0" \
    "pydantic-settings>=2.6.0" "aiosqlite>=0.20.0" "watchfiles>=1.0.0" \
    "httpx>=0.28.0" "pyyaml>=6.0" "python-multipart>=0.0.20" \
    "pymupdf>=1.25.0" "python-docx>=1.1.0" "python-pptx>=1.0.0" \
    "openpyxl>=3.1.0" "html2text>=2025.0.0" \
    "mcp[cli]>=1.8.0" "networkx>=3.6" "python-louvain>=0.16" "numpy>=1.26" \
    && mkdir -p /app/data

EXPOSE 8742

CMD ["python3", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8742", "--reload"]
