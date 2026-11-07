FROM python:3.12-slim

# Hugging Face runs Spaces as user 1000
RUN useradd -m -u 1000 user
WORKDIR /app

# CPU-only PyTorch, same version you tested with
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user

# download the embedding model during build, so startup is fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]