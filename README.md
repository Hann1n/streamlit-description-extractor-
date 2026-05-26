# PDF DESCRIPTION Extractor

Streamlit app that extracts values under the `DESCRIPTION` column from tables in uploaded PDFs.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

System dependencies:

- `poppler-utils` for `pdftoppm`
- `tesseract-ocr` for OCR

On Streamlit Community Cloud, these are installed from `packages.txt`.

## Run with Docker

```bash
docker compose up --build
```

Open:

```txt
http://localhost:8502
```

To stop:

```bash
docker compose down
```

The Docker image installs Poppler and Tesseract inside the container, so the host machine only needs Docker.
