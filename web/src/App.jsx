import { useState, useRef, useCallback, useEffect } from 'react'
import UploadZone from './components/UploadZone.jsx'
import PdfViewer from './components/PdfViewer.jsx'
import FieldList from './components/FieldList.jsx'
import Header from './components/Header.jsx'
import { analyzePdf, generatePdf } from './api.js'

const API_BASE = import.meta.env.VITE_API_URL || ''

export default function App() {
  // ── State ──
  const [pdfFile, setPdfFile] = useState(null)        // File object
  const [pdfData, setPdfData] = useState(null)         // ArrayBuffer for rendering
  const [fields, setFields] = useState(null)           // detected fields array or null
  const [pageCount, setPageCount] = useState(0)
  const [pageSizes, setPageSizes] = useState([])
  const [fieldCount, setFieldCount] = useState(0)
  const [loading, setLoading] = useState(false)        // analyzing
  const [generating, setGenerating] = useState(false)  // generating fillable
  const [error, setError] = useState(null)
  const [view, setView] = useState('upload')           // 'upload' | 'results'

  // ── Handle file selection ──
  const handleFile = useCallback(async (file) => {
    if (!file) return
    if (file.type !== 'application/pdf') {
      setError('Please upload a PDF file.')
      return
    }
    if (file.size > 50 * 1024 * 1024) {
      setError('File too large. Maximum size is 50 MB.')
      return
    }

    setError(null)
    setPdfFile(file)

    // Read file into ArrayBuffer for PDF.js rendering
    const arrayBuffer = await file.arrayBuffer()
    setPdfData(arrayBuffer)

    // Auto-analyze
    setLoading(true)
    setView('results')
    try {
      const result = await analyzePdf(API_BASE, file)
      setFields(result.fields || [])
      setPageCount(result.page_count || 0)
      setPageSizes(result.page_sizes || [])
      setFieldCount(result.field_count || 0)
    } catch (err) {
      setError(err.message || 'Failed to analyze PDF.')
      setFields([])
    } finally {
      setLoading(false)
    }
  }, [])

  // ── Download fillable PDF ──
  const handleDownload = useCallback(async () => {
    if (!pdfFile) return
    setGenerating(true)
    setError(null)
    try {
      const blob = await generatePdf(API_BASE, pdfFile)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = pdfFile.name.replace(/\.pdf$/i, '') + '_fillable.pdf'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.message || 'Failed to generate fillable PDF.')
    } finally {
      setGenerating(false)
    }
  }, [pdfFile])

  // ── Reset ──
  const handleReset = useCallback(() => {
    setPdfFile(null)
    setPdfData(null)
    setFields(null)
    setPageCount(0)
    setPageSizes([])
    setFieldCount(0)
    setError(null)
    setLoading(false)
    setGenerating(false)
    setView('upload')
  }, [])

  // ── Render ──
  return (
    <div className="app">
      <Header />

      <main className="main-content">
        {view === 'upload' && (
          <UploadZone onFile={handleFile} error={error} />
        )}

        {view === 'results' && (
          <div className="results-layout">
            {error && (
              <div className="error-banner">
                <span className="error-icon">⚠</span>
                {error}
                <button className="error-dismiss" onClick={() => setError(null)}>×</button>
              </div>
            )}

            <div className="results-main">
              <div className="toolbar">
                <div className="file-info">
                  <span className="file-icon">📄</span>
                  <span className="file-name">{pdfFile?.name}</span>
                  {pdfFile && (
                    <span className="file-size">
                      {(pdfFile.size / 1024).toFixed(0)} KB
                    </span>
                  )}
                </div>
                <div className="toolbar-actions">
                  <button
                    className="btn btn-secondary"
                    onClick={handleReset}
                    disabled={loading || generating}
                  >
                    ← New PDF
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={handleDownload}
                    disabled={loading || generating || !fields?.length}
                  >
                    {generating ? (
                      <><span className="spinner" /> Generating…</>
                    ) : (
                      <>⬇ Download Fillable PDF</>
                    )}
                  </button>
                </div>
              </div>

              <PdfViewer
                pdfData={pdfData}
                fields={fields}
                pageSizes={pageSizes}
                loading={loading}
              />
            </div>

            <aside className="sidebar">
              <FieldList
                fields={fields}
                fieldCount={fieldCount}
                loading={loading}
              />
            </aside>
          </div>
        )}
      </main>

      <footer className="footer">
        <span>pdfforge — Open-source PDF form field generator</span>
        <a href="https://github.com/infinitemindos-doai/pdfforge" target="_blank" rel="noopener">
          GitHub →
        </a>
      </footer>
    </div>
  )
}