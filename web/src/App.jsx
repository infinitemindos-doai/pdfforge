import { useState, useRef, useCallback, useEffect } from 'react'
import UploadZone from './components/UploadZone.jsx'
import PdfViewer from './components/PdfViewer.jsx'
import FieldList from './components/FieldList.jsx'
import Header from './components/Header.jsx'
import { analyzePdf, generatePdf } from './api.js'

const API_BASE = import.meta.env.VITE_API_URL || ''

// Maximum upload size: 50 MB — must match the backend limit
const MAX_FILE_SIZE = 50 * 1024 * 1024

// PDF magic bytes — every valid PDF starts with %PDF
const PDF_MAGIC = '%PDF'

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
  const errorBannerRef = useRef(null)

  // Move focus to the error banner when it appears (accessibility)
  useEffect(() => {
    if (error && errorBannerRef.current) {
      errorBannerRef.current.focus()
    }
  }, [error])

  /**
   * Validate a File object client-side before upload.
   * Checks:
   *   1. MIME type is application/pdf
   *   2. Extension is .pdf
   *   3. File size ≤ 50 MB
   *   4. File content starts with %PDF magic bytes
   *
   * @param {File} file - The file to validate
   * @returns {Promise<boolean>} - true if valid, false otherwise
   */
  const validateFile = useCallback(async (file) => {
    // Check MIME type (can be spoofed by the browser, but catches obvious mistakes)
    if (file.type !== 'application/pdf') {
      setError('Please upload a PDF file. Only PDF files are accepted.')
      return false
    }

    // Check extension
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('The file must have a .pdf extension.')
      return false
    }

    // Check file size
    if (file.size > MAX_FILE_SIZE) {
      setError('File too large. Maximum size is 50 MB.')
      return false
    }

    // Check PDF magic bytes — read the first 5 bytes of the file
    try {
      const header = file.slice(0, 5)
      const headerText = await header.text()
      if (!headerText.startsWith(PDF_MAGIC)) {
        setError('This file does not appear to be a valid PDF (missing PDF header).')
        return false
      }
    } catch {
      // If we can't read the header, let the server validate
      // (don't block the user — the backend will catch it)
    }

    return true
  }, [])

  // ── Handle file selection ──
  const handleFile = useCallback(async (file) => {
    if (!file) return

    // Validate before proceeding
    const isValid = await validateFile(file)
    if (!isValid) return

    setError(null)
    setPdfFile(file)

    // Read file into ArrayBuffer for PDF.js rendering
    try {
      const arrayBuffer = await file.arrayBuffer()
      setPdfData(arrayBuffer)
    } catch {
      setError('Failed to read the selected file. Please try again.')
      return
    }

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
  }, [validateFile])

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

  // ── Dismiss error ──
  const handleDismissError = useCallback(() => {
    setError(null)
  }, [])

  // ── Render ──
  return (
    <div className="app">
      <Header />

      <main className="main-content" role="main">
        {view === 'upload' && (
          <UploadZone onFile={handleFile} error={error} />
        )}

        {view === 'results' && (
          <div className="results-layout">
            {error && (
              <div
                className="error-banner"
                role="alert"
                aria-live="assertive"
                tabIndex={-1}
                ref={errorBannerRef}
              >
                <span className="error-icon" aria-hidden="true">⚠</span>
                {error}
                <button
                  className="error-dismiss"
                  onClick={handleDismissError}
                  aria-label="Dismiss error message"
                >
                  ×
                </button>
              </div>
            )}

            <div className="results-main">
              <div className="toolbar" role="toolbar" aria-label="PDF tools">
                <div className="file-info">
                  <span className="file-icon" aria-hidden="true">📄</span>
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
                    aria-label="Start over with a new PDF"
                  >
                    ← New PDF
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={handleDownload}
                    disabled={loading || generating || !fields?.length}
                    aria-label="Download the fillable PDF"
                  >
                    {generating ? (
                      <><span className="spinner" aria-hidden="true" /> Generating…</>
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

            <aside className="sidebar" aria-label="Detected fields sidebar">
              <FieldList
                fields={fields}
                fieldCount={fieldCount}
                loading={loading}
              />
            </aside>
          </div>
        )}
      </main>

      <footer className="footer" role="contentinfo">
        <span>pdfforge — Open-source PDF form field generator</span>
        <a
          href="https://github.com/infinitemindos-doai/pdfforge"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="View pdfforge on GitHub (opens in a new tab)"
        >
          GitHub →
        </a>
      </footer>
    </div>
  )
}
