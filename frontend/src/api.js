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

export async function listMaterials(token, courseId) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/materials`, {
    headers: authHeaders(token),
  })
  return handleResponse(res)
}

export async function uploadMaterial(token, courseId, file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE}/courses/${courseId}/materials`, {
    method: 'POST',
    headers: authHeaders(token), // no Content-Type -- browser sets multipart boundary automatically
    body: formData,
  })
  return handleResponse(res)
}

export async function listAnswers(token, courseId) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/answers`, {
    headers: authHeaders(token),
  })
  return handleResponse(res)
}

export async function uploadAnswer(token, courseId, questionId, studentIdentifier, file) {
  const formData = new FormData()
  formData.append('question_id', questionId)
  formData.append('student_identifier', studentIdentifier)
  formData.append('file', file)
  const res = await fetch(`${API_BASE}/courses/${courseId}/answers`, {
    method: 'POST',
    headers: authHeaders(token),
    body: formData,
  })
  return handleResponse(res)
}

export async function getSubmissionDetail(token, courseId, filename) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/submissions/${encodeURIComponent(filename)}`, {
    headers: authHeaders(token),
  })
  return handleResponse(res)
}

export async function gradeSubmission(token, courseId, filename) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/submissions/${encodeURIComponent(filename)}/grade`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  return handleResponse(res)
}

export async function submitReview(token, courseId, filename, decision) {
  const res = await fetch(`${API_BASE}/courses/${courseId}/submissions/${encodeURIComponent(filename)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(decision),
  })
  return handleResponse(res)
}