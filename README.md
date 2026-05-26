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

## Windows install

For Windows users, double-click this once:

```txt
Install-Windows.bat
```

Or run this from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-Windows.ps1
```

The installer checks or installs:

- Python 3.11
- Tesseract OCR
- Poppler PDF tools
- Python packages in `.venv`

After installation, double-click:

```txt
Start-Windows.bat
```

The installer also creates a desktop shortcut named:

```txt
PDF DESCRIPTION Extractor
```

The app opens at:

```txt
http://127.0.0.1:8501
```

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
