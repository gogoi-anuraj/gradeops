import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { getRubric, uploadRubric } from '../api.js'

const EXAMPLE_RUBRIC = `{
  "exam_id": "physics_quiz1",
  "reference_source": "Course textbook chapters covered",
  "questions": [
    {
      "question_id": "Q1",
      "prompt": "State Newton's First Law.",
      "total_marks": 4,
      "criteria": [
        { "criterion_id": "Q1_C1", "description": "Correct statement of the law", "marks": 2 },
        { "criterion_id": "Q1_C2", "description": "Explains inertial reference frame", "marks": 1 },
        { "criterion_id": "Q1_C3", "description": "Gives a valid real-world example", "marks": 1 }
      ]
    }
  ]
}`

export default function RubricPanel({ courseId }) {
  const { token } = useAuth()
  const [rubric, setRubric] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [jsonText, setJsonText] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef(null)

  useEffect(() => {
    refresh()
  }, [courseId])

  async function refresh() {
    setLoading(true)
    try {
      const data = await getRubric(token, courseId)
      setRubric(data)
      setEditing(data === null) // no rubric yet -- go straight to the edit form
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function startEditing() {
    setJsonText(rubric ? JSON.stringify(rubric.rubric_json, null, 2) : EXAMPLE_RUBRIC)
    setEditing(true)
    setError(null)
  }

  function handleFilePick(e) {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => setJsonText(event.target.result)
    reader.readAsText(file)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)

    let parsed
    try {
      parsed = JSON.parse(jsonText)
    } catch (parseErr) {
      setError(`Invalid JSON: ${parseErr.message}`)
      return
    }

    setSubmitting(true)
    try {
      await uploadRubric(token, courseId, parsed)
      await refresh()
    } catch (e) {
      setError(e.message) // includes backend validation errors, e.g. marks mismatch
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="loading-state">Loading rubric…</div>

  return (
    <div className="panel-section">
      <div className="panel-section-header">
        <h2>Rubric</h2>
        {!editing && rubric && (
          <button className="btn" onClick={startEditing}>Replace rubric</button>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {editing ? (
        <form onSubmit={handleSubmit} className="rubric-edit-form">
          <div className="rubric-edit-actions">
            <button
              type="button"
              className="btn"
              onClick={() => fileInputRef.current?.click()}
            >
              Choose JSON file…
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              onChange={handleFilePick}
              style={{ display: 'none' }}
            />
            <span className="rubric-edit-hint">or paste/edit JSON directly below</span>
          </div>

          <textarea
            className="rubric-textarea"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            spellCheck={false}
            rows={16}
          />

          <div style={{ display: 'flex', gap: 10 }}>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Uploading…' : 'Save rubric'}
            </button>
            {rubric && (
              <button type="button" className="btn" onClick={() => { setEditing(false); setError(null) }} disabled={submitting}>
                Cancel
              </button>
            )}
          </div>
        </form>
      ) : (
        <div className="rubric-view">
          {rubric.rubric_json.questions.map((q) => (
            <div key={q.question_id} className="rubric-question-block">
              <div className="rubric-question-header">
                <span className="mono">{q.question_id}</span>
                <span className="score-chip score-full">{q.total_marks} marks</span>
              </div>
              <p className="rubric-question-prompt">{q.prompt}</p>
              <div className="rubric-criteria-list">
                {q.criteria.map((c) => (
                  <div key={c.criterion_id} className="rubric-criterion-row">
                    <span className="mono rubric-criterion-id">{c.criterion_id}</span>
                    <span className="rubric-criterion-desc">{c.description}</span>
                    <span className="mono rubric-criterion-marks">{c.marks}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}