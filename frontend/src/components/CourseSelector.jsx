import { useState, useEffect } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { listCourses, createCourse } from '../api.js'

export default function CourseSelector({ onSelect }) {
  const { token } = useAuth()
  const [courses, setCourses] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    refresh()
  }, [])

  async function refresh() {
    setLoading(true)
    try {
      const data = await listCourses(token)
      setCourses(data)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(e) {
    e.preventDefault()
    setCreating(true)
    setError(null)
    try {
      const course = await createCourse(token, newName, newDescription)
      setNewName('')
      setNewDescription('')
      setShowCreateForm(false)
      await refresh()
      onSelect(course)
    } catch (e) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="course-selector-shell">
      <div className="course-selector-header">
        <div className="app-title">GRADEOPS</div>
        <div className="app-subtitle">Select a course to work in</div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="loading-state">Loading courses…</div>
      ) : (
        <div className="course-list">
          {courses.length === 0 && !showCreateForm && (
            <div className="empty-state">No courses yet. Create your first one below.</div>
          )}

          {courses.map((c) => (
            <button key={c.id} className="course-card" onClick={() => onSelect(c)}>
              <div className="course-card-name">{c.name}</div>
              {c.description && <div className="course-card-description">{c.description}</div>}
              <div className="course-card-meta">Created {new Date(c.created_at).toLocaleDateString()}</div>
            </button>
          ))}

          {showCreateForm ? (
            <form onSubmit={handleCreate} className="course-create-form">
              <div className="auth-field">
                <label htmlFor="course-name">Course name</label>
                <input
                  id="course-name"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  required
                  placeholder="e.g. Physics 101 — Fall 2026"
                  autoFocus
                />
              </div>
              <div className="auth-field">
                <label htmlFor="course-description">Description (optional)</label>
                <input
                  id="course-description"
                  type="text"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="e.g. Introductory mechanics"
                />
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <button type="submit" className="btn btn-primary" disabled={creating}>
                  {creating ? 'Creating…' : 'Create course'}
                </button>
                <button type="button" className="btn" onClick={() => setShowCreateForm(false)} disabled={creating}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button className="course-card course-card-new" onClick={() => setShowCreateForm(true)}>
              + Create a new course
            </button>
          )}
        </div>
      )}
    </div>
  )
}