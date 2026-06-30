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
  table_cell: { stroke: '#10ac84', fill: 'rgba(16, 172, 132, 0.15)', label: 'Table Cell' },
}

export default function PdfViewer({ pdfData, fields, pageSizes, loading }) {
  const [pdfDoc, setPdfDoc] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [renderedPages, setRenderedPages] = useState({})
  const canvasRefs = useRef({})

  // Load PDF document
  useEffect(() => {
    if (!pdfData) return
    setPdfDoc(null)
    setRenderedPages({})

    const loadingTask = pdfjsLib.getDocument({ data: pdfData.slice(0) })
    loadingTask.promise.then((doc) => {
      setPdfDoc(doc)
      setCurrentPage(1)
    }).catch((err) => {
      console.error('PDF load error:', err)
    })

    return () => {
      setPdfDoc(null)
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
      const viewport = page.getViewport({ scale: 1.5 })
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

    renderPage(currentPage).catch(console.error)
  }, [pdfDoc, currentPage])

  // Also render adjacent pages for smooth scrolling
  useEffect(() => {
    if (!pdfDoc) return
    [currentPage - 1, currentPage + 1].forEach((p) => {
      if (p >= 1 && p <= pdfDoc.numPages && !renderedPages[p]) {
        const renderPage = async () => {
          const canvas = canvasRefs.current[p]
          if (!canvas) return
          const page = await pdfDoc.getPage(p)
          const viewport = page.getViewport({ scale: 1.5 })
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
        renderPage().catch(console.error)
      }
    })
  }, [pdfDoc, currentPage, renderedPages])

  const numPages = pdfDoc?.numPages || 0

  // Get scale: PDF.js renders at 1.5x, PDF coords are at 1x
  // So to overlay fields correctly: field_coords * (rendered_width / pdf_width)
  const getScale = (pageNum) => {
    if (!renderedPages[pageNum] || !pageSizes[pageNum - 1]) return 1.5
    return renderedPages[pageNum].width / pageSizes[pageNum - 1].width
  }

  const pageFields = (fields || []).filter((f) => f.page === currentPage - 1)

  return (
    <div className="pdf-viewer">
      {loading && (
        <div className="pdf-loading">
          <div className="spinner" />
          <p>Analyzing PDF…</p>
        </div>
      )}

      {pdfDoc && (
        <>
          <div className="pdf-controls">
            <button
              className="page-btn"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
            >
              ← Prev
            </button>
            <span className="page-indicator">
              Page {currentPage} / {numPages}
            </span>
            <button
              className="page-btn"
              onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
              disabled={currentPage >= numPages}
            >
              Next →
            </button>
          </div>

          <div className="pdf-canvas-wrapper">
            {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
              <div
                key={pageNum}
                className={`pdf-page-container ${pageNum === currentPage ? 'active' : 'inactive'}`}
              >
                <canvas
                  ref={(el) => { if (el) canvasRefs.current[pageNum] = el }}
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
                        >
                          <span className="field-type-badge" style={{ backgroundColor: color.stroke }}>
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

      {!pdfDoc && !loading && (
        <div className="pdf-placeholder">
          <p>Upload a PDF to see preview</p>
        </div>
      )}
    </div>
  )
}