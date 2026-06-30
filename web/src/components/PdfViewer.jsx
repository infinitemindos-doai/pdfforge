import { useEffect, useState, useRef } from 'react'
import * as pdfjsLib from 'pdfjs-dist'

// Use the worker bundled with pdfjs-dist
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

// Type colors and icons
const TYPE_COLORS = {
  text: { stroke: '#00d4ff', fill: 'rgba(0, 212, 255, 0.15)', label: 'Text' },
  checkbox: { stroke: '#ff9f43', fill: 'rgba(255, 159, 67, 0.20)', label: 'Checkbox' },
  radio: { stroke: '#ee5a6f', fill: 'rgba(238, 90, 111, 0.20)', label: 'Radio' },
  table_cell: { stroke: '#10ac84', fill: 'rgba(16, 172, 132, 0.15)', label: 'Table Cell' },
  textarea: { stroke: '#a78bfa', fill: 'rgba(167, 139, 250, 0.15)', label: 'Text Area' },
}

export default function PdfViewer({ pdfData, fields, pageSizes, loading }) {
  const [pdfDoc, setPdfDoc] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [renderedPages, setRenderedPages] = useState({})
  const [pdfError, setPdfError] = useState(null)
  const canvasRefs = useRef({})

  const [zoomLevel, setZoomLevel] = useState(1.5)

  // Load PDF document
  useEffect(() => {
    if (!pdfData) return
    setPdfDoc(null)
    setRenderedPages({})
    setPdfError(null)

    const loadingTask = pdfjsLib.getDocument({ data: pdfData.slice(0) })
    loadingTask.promise.then((doc) => {
      setPdfDoc(doc)
      setCurrentPage(1)
    }).catch((err) => {
      console.error('PDF load error:', err)
      setPdfError('Failed to load PDF preview. The file may be corrupted or unsupported.')
    })

    return () => {
      // Clean up the PDF document to free memory
      setPdfDoc((prevDoc) => {
        if (prevDoc) {
          try {
            prevDoc.destroy()
          } catch {
            // ignore cleanup errors
          }
        }
        return null
      })
      setRenderedPages({})
    }
  }, [pdfData])

  // Render current page
  useEffect(() => {
    if (!pdfDoc) return

    const renderPage = async (pageNum) => {
      const canvas = canvasRefs.current[pageNum]
      if (!canvas) return

      const page = await pdfDoc.getPage(pageNum)
      const viewport = page.getViewport({ scale: zoomLevel })
      const ctx = canvas.getContext('2d')

      // Use device pixel ratio for sharpness
      const dpr = window.devicePixelRatio || 1
      canvas.width = viewport.width * dpr
      canvas.height = viewport.height * dpr
      canvas.style.width = `${viewport.width / dpr}px`
      canvas.style.height = `${viewport.height / dpr}px`

      await page.render({
        canvasContext: ctx,
        viewport: viewport.clone({ scale: viewport.scale * dpr }),
      }).promise

      setRenderedPages((prev) => ({ ...prev, [pageNum]: { width: viewport.width, height: viewport.height } }))
    }

    renderPage(currentPage).catch((err) => {
      console.error('Page render error:', err)
    })
  }, [pdfDoc, currentPage, zoomLevel])

  // Also render adjacent pages for smooth scrolling
  useEffect(() => {
    if (!pdfDoc) return
    [currentPage - 1, currentPage + 1].forEach((p) => {
      if (p >= 1 && p <= pdfDoc.numPages && !renderedPages[p]) {
        const renderPage = async () => {
          const canvas = canvasRefs.current[p]
          if (!canvas) return
          const page = await pdfDoc.getPage(p)
          const viewport = page.getViewport({ scale: zoomLevel })
          const ctx = canvas.getContext('2d')
          const dpr = window.devicePixelRatio || 1
          canvas.width = viewport.width * dpr
          canvas.height = viewport.height * dpr
          canvas.style.width = `${viewport.width / dpr}px`
          canvas.style.height = `${viewport.height / dpr}px`
          await page.render({
            canvasContext: ctx,
            viewport: viewport.clone({ scale: viewport.scale * dpr }),
          }).promise
          setRenderedPages((prev) => ({ ...prev, [p]: { width: viewport.width, height: viewport.height } }))
        }
        renderPage().catch((err) => {
          console.error('Adjacent page render error:', err)
        })
      }
    })
  }, [pdfDoc, currentPage, renderedPages, zoomLevel])

  const numPages = pdfDoc?.numPages || 0

  // Get scale: PDF.js renders at 1.5x, PDF coords are at 1x
  // So to overlay fields correctly: field_coords * (rendered_width / pdf_width)
  const getScale = (pageNum) => {
    if (!renderedPages[pageNum] || !pageSizes[pageNum - 1]) return zoomLevel
    const dpr = window.devicePixelRatio || 1
    // renderedPages stores viewport.width (PDF width * scale), but field positions
    // need to map to CSS pixels (viewport.width / dpr). So:
    // css_scale = (viewport.width / dpr) / pdf_width = (pdf_width * scale / dpr) / pdf_width = scale / dpr
    return (renderedPages[pageNum].width / pageSizes[pageNum - 1].width) / dpr
  }

  const pageFields = (fields || []).filter((f) => f.page === currentPage - 1)

  const goToPrevPage = () => setCurrentPage((p) => Math.max(1, p - 1))
  const goToNextPage = () => setCurrentPage((p) => Math.min(numPages, p + 1))

  // Keyboard navigation for the PDF viewer
  const handleKeyDown = (e) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      goToPrevPage()
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      goToNextPage()
    }
  }

  return (
    <div className="pdf-viewer" onKeyDown={handleKeyDown} tabIndex={0} aria-label="PDF preview — use arrow keys to navigate pages">
      {loading && (
        <div className="pdf-loading" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true" />
          <p>Analyzing PDF…</p>
        </div>
      )}

      {pdfError && (
        <div className="pdf-placeholder" role="alert" aria-live="assertive">
          <p>{pdfError}</p>
        </div>
      )}

      {pdfDoc && (
        <>
          <div className="pdf-controls" role="navigation" aria-label="Page navigation">
            <button
              className="page-btn"
              onClick={goToPrevPage}
              disabled={currentPage <= 1}
              aria-label="Previous page"
            >
              ← Prev
            </button>
            <span className="page-indicator" aria-current="page">
              Page {currentPage} / {numPages}
            </span>
            <button
              className="page-btn"
              onClick={goToNextPage}
              disabled={currentPage >= numPages}
              aria-label="Next page"
            >
              Next →
            </button>
            <div className="zoom-controls" role="group" aria-label="Zoom controls">
              <button
                className="page-btn"
                onClick={() => setZoomLevel(z => Math.max(0.5, z - 0.25))}
                disabled={zoomLevel <= 0.5}
                aria-label="Zoom out"
              >
                −
              </button>
              <span className="zoom-level">{Math.round(zoomLevel * 100)}%</span>
              <button
                className="page-btn"
                onClick={() => setZoomLevel(z => Math.min(3.0, z + 0.25))}
                disabled={zoomLevel >= 3.0}
                aria-label="Zoom in"
              >
                +
              </button>
            </div>
          </div>

          <div className="pdf-canvas-wrapper">
            {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
              <div
                key={pageNum}
                className={`pdf-page-container ${pageNum === currentPage ? 'active' : 'inactive'}`}
              >
                <canvas
                  ref={(el) => { if (el) canvasRefs.current[pageNum] = el }}
                  role="img"
                  aria-label={`Page ${pageNum} of ${numPages}`}
                />
                {pageNum === currentPage && pageFields.length > 0 && renderedPages[pageNum] && (
                  <div className="field-overlay" style={{ width: canvasRefs.current[pageNum]?.style.width, height: canvasRefs.current[pageNum]?.style.height }}>
                    {pageFields.map((field, idx) => {
                      const scale = getScale(pageNum)
                      const color = TYPE_COLORS[field.type] || TYPE_COLORS.text
                      const left = field.x * scale
                      const top = field.y * scale
                      const width = field.width * scale
                      const height = field.height * scale

                      return (
                        <div
                          key={idx}
                          className="field-box"
                          style={{
                            left: `${left}px`,
                            top: `${top}px`,
                            width: `${width}px`,
                            height: `${height}px`,
                            borderColor: color.stroke,
                            backgroundColor: color.fill,
                          }}
                          title={field.label || field.name}
                          role="img"
                          aria-label={`${color.label} field: ${field.label || field.name || `Field ${idx + 1}`}`}
                        >
                          <span className="field-type-badge" style={{ backgroundColor: color.stroke }} aria-hidden="true">
                            {field.type === 'checkbox' ? '☑' : field.type === 'table_cell' ? '▦' : 'T'}
                          </span>
                          {field.label && (
                            <span className="field-label-tooltip">{field.label}</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {!pdfDoc && !loading && !pdfError && (
        <div className="pdf-placeholder">
          <p>Upload a PDF to see preview</p>
        </div>
      )}
    </div>
  )
}
