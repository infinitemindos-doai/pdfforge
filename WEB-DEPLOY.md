# pdfforge — Web App Setup & Deployment

## Quick Start (Local Dev)

### Backend (FastAPI)

```bash
cd pdfforge
source .venv/bin/activate
pip install -r api/requirements.txt
uvicorn api.app:app --port 8000 --reload
```

Backend runs at http://localhost:8000
API docs at http://localhost:8000/docs

### Frontend (React + Vite)

```bash
cd pdfforge/web
npm install
npm run dev
```

Frontend runs at http://localhost:5173
The Vite dev server proxies `/api/*` to `http://localhost:8000`.

## Architecture

```
pdfforge/
├── detector.py          # CLI — field detection engine
├── generator.py         # CLI — fillable PDF generator
├── main.py              # CLI — command-line interface
├── api/                 # Backend — FastAPI
│   ├── __init__.py
│   ├── app.py           # REST endpoints
│   └── requirements.txt
├── web/                 # Frontend — React + Vite
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── .env.production
│   ├── public/
│   │   └── favicon.svg
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api.js
│       ├── styles.css
│       └── components/
│           ├── Header.jsx
│           ├── UploadZone.jsx
│           ├── PdfViewer.jsx
│           └── FieldList.jsx
├── render.yaml          # Render.com backend deploy config
├── .github/workflows/
│   └── deploy-frontend.yml  # GitHub Pages frontend deploy
└── sample_form.pdf      # Test PDF
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/samples` | List available sample PDFs |
| POST | `/api/analyze-pdf` | Upload PDF → get detected field JSON |
| POST | `/api/generate-pdf` | Upload PDF → get fillable PDF download |

### Example Usage

```bash
# Analyze a PDF
curl -X POST http://localhost:8000/api/analyze-pdf \
  -F "file=@sample_form.pdf"

# Generate fillable PDF
curl -X POST http://localhost:8000/api/generate-pdf \
  -F "file=@sample_form.pdf" \
  -o test_fillable.pdf
```

## Deployment

### Backend → Render.com

1. Go to https://render.com and create an account
2. Click "New" → "Blueprint"
3. Connect your GitHub repo: `infinitemindos-doai/pdfforge`
4. Select the `render.yaml` file
5. Deploy — Render will:
   - Install Python dependencies from `api/requirements.txt`
   - Start `uvicorn api.app:app --host 0.0.0.0 --port $PORT`
   - Provide a URL like `https://pdfforge-api.onrender.com`
6. Verify: `curl https://pdfforge-api.onrender.com/api/health`

### Frontend → GitHub Pages

1. Go to your GitHub repo Settings → Pages
2. Source: "GitHub Actions"
3. The workflow in `.github/workflows/deploy-frontend.yml` will:
   - Install npm dependencies
   - Build the Vite app with `VITE_API_URL` pointing to your Render backend
   - Deploy `web/dist/` to GitHub Pages
4. Your frontend will be at: `https://infinitemindos-doai.github.io/pdfforge/`

### Updating the API URL

If your Render URL differs, update `web/.env.production`:

```env
VITE_API_URL=https://your-render-url.onrender.com
```

And update the `VITE_API_URL` in `.github/workflows/deploy-frontend.yml` accordingly.

## Features

- 🎨 Dark theme UI with electric blue accents
- 📄 Drag-and-drop PDF upload
- 🔍 Auto-detect text fields, checkboxes, and table cells
- 👁️ Visual field overlay on rendered PDF pages
- 📋 Field list sidebar with type icons and labels
- ⬇️ One-click download of fillable PDF
- 📱 Mobile responsive
- 🔒 Files processed and cleaned up server-side
- 🚀 Free tier: Render (backend) + GitHub Pages (frontend)