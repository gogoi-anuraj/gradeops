const API_BASE = 'http://127.0.0.1:8000'

async function handleResponse(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` }
}

export async function signup(email, password, name) {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, name }),
  })
  return handleResponse(res)
}

export async function login(email, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return handleResponse(res)
}

export async function getMe(token) {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: authHeaders(token),
  })
  return handleResponse(res)
}

export async function listCourses(token) {
  const res = await fetch(`${API_BASE}/courses`, {
    headers: authHeaders(token),
  })
  return handleResponse(res)
}

export async function createCourse(token, name, description) {
  const res = await fetch(`${API_BASE}/courses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ name, description: description || null }),
  })
  return handleResponse(res)
}

export async function getRubric(token, courseId) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/rubric`, {
    headers: authHeaders(token),
  })
  if (res.status === 404) return null // no rubric uploaded yet -- not an error
  return handleResponse(res)
}

export async function uploadRubric(token, courseId, rubric) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/rubric`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(rubric),
  })
  return handleResponse(res)
}