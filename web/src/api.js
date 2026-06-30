/**
 * API client for pdfforge backend.
 * In dev, Vite proxy routes /api → localhost:8000.
 * In prod, VITE_API_URL points to the Render backend.
 */

export async function analyzePdf(baseUrl, file) {
  const url = baseUrl
    ? `${baseUrl}/api/analyze-pdf`
    : '/api/analyze-pdf'

  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(url, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Server error (${res.status})`)
  }

  return res.json()
}

export async function generatePdf(baseUrl, file, fieldsJson = null) {
  const url = baseUrl
    ? `${baseUrl}/api/generate-pdf`
    : '/api/generate-pdf'

  const formData = new FormData()
  formData.append('file', file)
  if (fieldsJson) {
    formData.append('fields_json', JSON.stringify(fieldsJson))
  }

  const res = await fetch(url, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Server error (${res.status})`)
  }

  return res.blob()
}

export async function checkHealth(baseUrl) {
  const url = baseUrl
    ? `${baseUrl}/api/health`
    : '/api/health'

  const res = await fetch(url)
  return res.json()
}