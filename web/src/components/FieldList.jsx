const TYPE_ICONS = {
  text: { icon: 'T', color: '#00d4ff', label: 'Text Field' },
  checkbox: { icon: '☑', color: '#ff9f43', label: 'Checkbox' },
  radio: { icon: '◯', color: '#ee5a6f', label: 'Radio Button' },
  table_cell: { icon: '▦', color: '#10ac84', label: 'Table Cell' },
  textarea: { icon: '¶', color: '#a78bfa', label: 'Text Area' },
}

export default function FieldList({ fields, fieldCount, loading }) {
  if (loading) {
    return (
      <div className="field-list">
        <div className="field-list-header">
          <h3>Detected Fields</h3>
        </div>
        <div className="field-list-loading" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true" />
          <p>Detecting fields…</p>
        </div>
      </div>
    )
  }

  if (!fields || fields.length === 0) {
    return (
      <div className="field-list">
        <div className="field-list-header">
          <h3>Detected Fields</h3>
          <span className="field-count">0</span>
        </div>
        <div className="field-list-empty">
          <p>No fields detected.</p>
          <p className="field-list-hint">
            This PDF might not have detectable form areas.
            Try uploading a different PDF with lines, checkboxes, or tables.
          </p>
        </div>
      </div>
    )
  }

  // Group fields by type
  const byType = fields.reduce((acc, f) => {
    const t = f.type || 'text'
    if (!acc[t]) acc[t] = []
    acc[t].push(f)
    return acc
  }, {})

  return (
    <div className="field-list">
      <div className="field-list-header">
        <h3>Detected Fields</h3>
        <span className="field-count" aria-label={`${fieldCount} fields detected`}>{fieldCount}</span>
      </div>

      <div className="field-summary">
        {Object.entries(byType).map(([type, items]) => {
          const info = TYPE_ICONS[type] || TYPE_ICONS.text
          return (
            <div key={type} className="summary-chip" style={{ borderColor: info.color }}>
              <span className="chip-icon" style={{ color: info.color }} aria-hidden="true">{info.icon}</span>
              <span className="chip-count">{items.length}</span>
              <span className="chip-label">{info.label}</span>
            </div>
          )
        })}
      </div>

      <div className="field-items" role="list" aria-label="List of detected form fields">
        {fields.map((field, idx) => {
          const info = TYPE_ICONS[field.type] || TYPE_ICONS.text
          return (
            <div key={idx} className="field-item" role="listitem">
              <div className="field-item-icon" style={{ color: info.color }} aria-hidden="true">
                {info.icon}
              </div>
              <div className="field-item-content">
                <span className="field-item-label">
                  {field.label || field.name || `Field ${idx + 1}`}
                </span>
                <span className="field-item-meta">
                  {info.label} · Page {field.page + 1}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
