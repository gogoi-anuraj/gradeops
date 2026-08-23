const API_BASE = 'http://127.0.0.1:8000'

async function handleResponse(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function listSubmissions() {
  const res = await fetch(`${API_BASE}/submissions`)
  return handleResponse(res)
}

export async function getSubmission(filename) {
  const res = await fetch(`${API_BASE}/submissions/${encodeURIComponent(filename)}`)
  return handleResponse(res)
}

export async function gradeSubmission(filename) {
  const res = await fetch(`${API_BASE}/submissions/${encodeURIComponent(filename)}/grade`, {
    method: 'POST',
  })
  return handleResponse(res)
}

export async function submitReview(filename, decision) {
  const res = await fetch(`${API_BASE}/submissions/${encodeURIComponent(filename)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(decision),
  })
  return handleResponse(res)
}