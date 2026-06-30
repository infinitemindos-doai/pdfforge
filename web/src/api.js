/**
 * API client for pdfforge backend.
 * In dev, Vite proxy routes /api → localhost:8000.
 * In prod, VITE_API_URL points to the Render backend.
 */

/**
 * Default timeout for API requests (30 seconds).
 * PDF analysis/generation may take time on large files.
 */
const DEFAULT_TIMEOUT_MS = 30_000

/**
 * Wrapper around fetch() that adds:
 * - Network error handling (offline, DNS failure, connection refused)
 * - Request timeout via AbortController
 *
 * @param {string} url - The URL to fetch
 * @param {RequestInit} options - Standard fetch options
 * @param {number} timeoutMs - Timeout in milliseconds
 * @returns {Promise<Response>} - The fetch Response on success
 * @throws {Error} - On network failure or timeout
 */
async function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    })
    return res
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out. The server may be slow or unresponsive — please try again.')
    }
    // Network errors (offline, DNS failure, connection refused)
    throw new Error('Network error: unable to reach the server. Please check your connection and try again.')
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * Extract a user-friendly error message from a failed HTTP response.
 * Tries to parse JSON { detail: "..." } first, falls back to status text.
 *
 * @param {Response} res - The non-OK fetch Response
 * @returns {Promise<string>} - A human-readable error message
 */
async function extractErrorMessage(res) {
  try {
    const data = await res.json()
    if (data.detail) return data.detail
    if (data.message) return data.message
  } catch {
    // Response body wasn't JSON — fall through to status-based message
  }
  // Map common HTTP status codes to friendly messages
  const statusMessages = {
    400: 'Bad request — the server rejected the input.',
    401: 'Unauthorized — authentication required.',
    403: 'Forbidden — you do not have access to this resource.',
    404: 'Not found — the requested resource does not exist.',
    413: 'File too large. Maximum size is 50 MB.',
    422: 'The server could not process this PDF. It may be corrupted or invalid.',
    500: 'Server error — something went wrong on our end. Please try again.',
    502: 'Server is temporarily unavailable. Please try again in a moment.',
    503: 'Service unavailable — the server is overloaded. Please try again shortly.',
    504: 'Server timed out while processing your request. Please try again.',
  }
  return statusMessages[res.status] || `Server error (${res.status})`
}

export async function analyzePdf(baseUrl, file) {
  const url = baseUrl
    ? `${baseUrl}/api/analyze-pdf`
    : '/api/analyze-pdf'

  const formData = new FormData()
  formData.append('file', file)

  const res = await fetchWithTimeout(url, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const msg = await extractErrorMessage(res)
    throw new Error(msg)
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

  // Generation may take longer for large PDFs
  const res = await fetchWithTimeout(url, {
    method: 'POST',
    body: formData,
  }, 60_000)

  if (!res.ok) {
    const msg = await extractErrorMessage(res)
    throw new Error(msg)
  }

  return res.blob()
}

export async function checkHealth(baseUrl) {
  const url = baseUrl
    ? `${baseUrl}/api/health`
    : '/api/health'

  const res = await fetchWithTimeout(url)
  return res.json()
}
