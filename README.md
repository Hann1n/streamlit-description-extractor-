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
