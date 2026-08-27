import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { getRubric, listAnswers, uploadAnswer, gradeSubmission } from '../api.js'

const STATUS_LABELS = {
  ungraded: 'Ungraded',
  graded: 'Needs review',
  accepted: 'Accepted',
  overridden: 'Overridden',
}

function filenameToIdentifier(filename) {
  return filename.replace(/\.[^/.]+$/, '') // strip extension
}

function formatScore(a) {
  if (a.ta_status === 'overridden' && a.ta_override_score != null) {
    const originalMax = a.final_grading ? a.final_grading.total_max : null
    return {
      primary: originalMax != null ? `${a.ta_override_score}/${originalMax}` : `${a.ta_override_score}`,
      original: a.final_grading ? `${a.final_grading.total_score}/${a.final_grading.total_max}` : null,
    }
  }
  if (!a.final_grading) return { primary: '—', original: null }
  return { primary: `${a.final_grading.total_score}/${a.final_grading.total_max}`, original: null }
}

export default function AnswersPanel({ courseId, onSelectSubmission }) {
  const { token } = useAuth()
  const [rubric, setRubric] = useState(null)
  const [answers, setAnswers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedQuestionId, setSelectedQuestionId] = useState('')
  const [uploadQueue, setUploadQueue] = useState([])
  const [uploading, setUploading] = useState(false)
  const [gradingFilename, setGradingFilename] = useState(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    refresh()
  }, [courseId])

  async function refresh() {
    setLoading(true)
    try {
      const [rubricData, answersData] = await Promise.all([
        getRubric(token, courseId),
        listAnswers(token, courseId),
      ])
      setRubric(rubricData)
      setAnswers(answersData)
      if (rubricData && !selectedQuestionId) {
        setSelectedQuestionId(rubricData.rubric_json.questions[0]?.question_id || '')
      }
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleFilesSelected(e) {
    const files = Array.from(e.target.files)
    if (files.length === 0) return

    setUploading(true)
    setError(null)
    setUploadQueue(files.map((f) => ({ filename: f.name, status: 'pending' })))

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const studentIdentifier = filenameToIdentifier(file.name)
      setUploadQueue((prev) => prev.map((item, idx) => idx === i ? { ...item, status: 'uploading' } : item))
      try {
        await uploadAnswer(token, courseId, selectedQuestionId, studentIdentifier, file)
        setUploadQueue((prev) => prev.map((item, idx) => idx === i ? { ...item, status: 'success' } : item))
      } catch (e) {
        setUploadQueue((prev) => prev.map((item, idx) => idx === i ? { ...item, status: 'error', error: e.message } : item))
      }
    }

    setUploading(false)
    await refresh()
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleGrade(filename) {
    setGradingFilename(filename)
    setError(null)
    try {
      await gradeSubmission(token, courseId, filename)
      await refresh()
    } catch (e) {
      setError(`Couldn't grade ${filename}: ${e.message}`)
    } finally {
      setGradingFilename(null)
    }
  }

  if (loading) return <div className="loading-state">Loading student answers…</div>

  if (!rubric) {
    return (
      <div className="panel-section">
        <div className="panel-section-header"><h2>Student Answers</h2></div>
        <div className="empty-state">Upload a rubric first before uploading student answers.</div>
      </div>
    )
  }

  return (
    <div className="panel-section">
      <div className="panel-section-header">
        <h2>Student Answers</h2>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="answer-upload-controls">
        <select
          className="answer-question-select"
          value={selectedQuestionId}
          onChange={(e) => setSelectedQuestionId(e.target.value)}
          disabled={uploading}
        >
          {rubric.rubric_json.questions.map((q) => (
            <option key={q.question_id} value={q.question_id}>{q.question_id}</option>
          ))}
        </select>
        <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? 'Uploading…' : 'Upload answer images'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".jpg,.jpeg,.png,.webp"
          multiple
          onChange={handleFilesSelected}
          style={{ display: 'none' }}
        />
      </div>
      <p className="answer-upload-hint">
        All selected files are uploaded for question <strong>{selectedQuestionId}</strong>.
        Name each file by student ID or roll number (e.g. <span className="mono">23052.jpg</span>) --
        that becomes the student identifier automatically.
      </p>

      {uploadQueue.length > 0 && (
        <div className="upload-queue">
          {uploadQueue.map((item, i) => (
            <div key={i} className={`upload-queue-row upload-status-${item.status}`}>
              <span className="mono">{item.filename}</span>
              <span className="upload-status-label">
                {item.status === 'pending' && 'Queued'}
                {item.status === 'uploading' && 'Uploading + transcribing…'}
                {item.status === 'success' && '✓ Uploaded'}
                {item.status === 'error' && `✗ ${item.error}`}
              </span>
            </div>
          ))}
        </div>
      )}

      {answers.length === 0 ? (
        <div className="empty-state">No student answers uploaded yet.</div>
      ) : (
        <div className="submission-table">
          {answers.map((a) => {
            const isClickable = a.ta_status !== 'ungraded'
            return (
              <div
                key={a.filename}
                className={`answer-row ${isClickable ? 'answer-row-clickable' : ''}`}
                onClick={() => isClickable && onSelectSubmission(a.filename)}
              >
                <span className="mono">{a.filename}</span>
                <span className="mono answer-question-id">{a.question_id}</span>
                <span className="answer-student">{a.student_identifier || '—'}</span>
                <span className={`status-pill ${a.ta_status}`}>
                  {STATUS_LABELS[a.ta_status] || a.ta_status}
                </span>
                <span className="answer-score">
                  {formatScore(a).primary}
                  {formatScore(a).original && (
                    <span className="row-score-original"> (was {formatScore(a).original})</span>
                  )}
                </span>
                <span className="answer-action">
                  {a.ta_status === 'ungraded' ? (
                    <button
                      className="btn btn-primary"
                      onClick={(e) => { e.stopPropagation(); handleGrade(a.filename) }}
                      disabled={gradingFilename === a.filename}
                    >
                      {gradingFilename === a.filename ? 'Grading…' : 'Grade'}
                    </button>
                  ) : (
                    <span className="answer-review-link">Review →</span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}