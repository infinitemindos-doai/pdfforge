import { useState, useCallback, useRef } from 'react'

export default function UploadZone({ onFile, error }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(false)
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(false)

    const files = e.dataTransfer.files
    if (files && files.length > 0) {
      onFile(files[0])
    }
  }, [onFile])

  const handleClick = useCallback(() => {
    inputRef.current?.click()
  }, [])

  const handleChange = useCallback((e) => {
    const file = e.target.files?.[0]
    if (file) onFile(file)
    // Reset so selecting the same file again still fires
    e.target.value = ''
  }, [onFile])

  return (
    <div className="upload-container">
      <div
        className={`upload-zone ${dragging ? 'dragging' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && handleClick()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={handleChange}
          style={{ display: 'none' }}
        />
        <div className="upload-icon">
          <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
            <rect x="16" y="8" width="48" height="64" rx="6" fill="none" stroke="#00d4ff" stroke-width="3"/>
            <line x1="26" y1="24" x2="54" y2="24" stroke="#00d4ff" stroke-width="3" stroke-linecap="round"/>
            <line x1="26" y1="34" x2="48" y2="34" stroke="#00d4ff" stroke-width="3" stroke-linecap="round"/>
            <rect x="26" y="44" width="12" height="12" rx="2" fill="none" stroke="#00d4ff" stroke-width="3"/>
            <line x1="42" y1="50" x2="54" y2="50" stroke="#00d4ff" stroke-width="3" stroke-linecap="round"/>
            <path d="M40 58 L40 70 M34 64 L40 70 L46 64" stroke="#00d4ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" transform="translate(0, -2)"/>
          </svg>
        </div>
        <h2 className="upload-title">Drop your PDF here</h2>
        <p className="upload-subtitle">or click to browse</p>
        <p className="upload-hint">Max 50 MB · PDF files only</p>
      </div>

      {error && (
        <div className="upload-error">
          <span>⚠</span> {error}
        </div>
      )}

      <div className="upload-features">
        <div className="feature">
          <span className="feature-icon">🔍</span>
          <span className="feature-text">Auto-detect form fields</span>
        </div>
        <div className="feature">
          <span className="feature-icon">⬇</span>
          <span className="feature-text">Download fillable PDF</span>
        </div>
        <div className="feature">
          <span className="feature-icon">🔒</span>
          <span className="feature-text">Files processed & deleted</span>
        </div>
      </div>
    </div>
  )
}