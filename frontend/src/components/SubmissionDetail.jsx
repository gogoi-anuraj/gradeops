import { useEffect, useState } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { getSubmissionDetail, submitReview } from '../api.js'

function scoreQuality(awarded, max) {
  if (max === 0) return 'zero'
  if (awarded === max) return 'full'
  if (awarded === 0) return 'zero'
  return 'partial'
}

function ScoreChip({ awarded, max }) {
  const quality = scoreQuality(awarded, max)
  return <span className={`score-chip score-${quality}`}>{awarded}/{max}</span>
}

export default function SubmissionDetail({ courseId, filename, onBack, onReviewed }) {
  const { token } = useAuth()
  const [submission, setSubmission] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showOverrideForm, setShowOverrideForm] = useState(false)
  const [overrideScore, setOverrideScore] = useState('')
  const [overrideNotes, setOverrideNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    getSubmissionDetail(token, courseId, filename)
      .then((data) => { if (!cancelled) setSubmission(data) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [courseId, filename])

  async function handleAccept() {
    setSubmitting(true)
    setError(null)
    try {
      await submitReview(token, courseId, filename, { status: 'accepted' })
      onReviewed()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleOverrideSubmit() {
    const scoreValue = parseFloat(overrideScore)
    if (Number.isNaN(scoreValue)) {
      setError('Enter a valid numeric score before submitting an override.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await submitReview(token, courseId, filename, {
        status: 'overridden',
        override_score: scoreValue,
        notes: overrideNotes || null,
      })
      onReviewed()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="loading-state">Loading submission…</div>
  if (error && !submission) return <div className="error-banner">{error}</div>
  if (!submission) return null

  const grading = submission.final_grading
  const alreadyReviewed = submission.ta_status === 'accepted' || submission.ta_status === 'overridden'

  return (
    <div>
      <button className="btn" onClick={onBack}>← Back to list</button>

      <div className="detail-header">
        <div>
          <div className="detail-filename">{submission.filename}</div>
          <div className="detail-meta">
            Question {submission.question_id}
            {submission.student_identifier && <> · {submission.student_identifier}</>}
            {submission.top_retrieval_similarity != null && (
              <> · retrieval similarity <span className="mono">{submission.top_retrieval_similarity.toFixed(3)}</span></>
            )}
          </div>
        </div>
        {grading && <div className="detail-total"><ScoreChip awarded={grading.total_score} max={grading.total_max} /></div>}
      </div>

      {submission.flagged_for_review && (
        <div className="flag-banner">
          <strong>Flagged for review:</strong> {submission.flag_reason}
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      <div className="detail-columns">
        <div className="detail-panel">
          <div className="panel-title">Student's transcribed answer</div>
          <div className="panel-body answer-text">{submission.student_answer}</div>
        </div>

        <div className="detail-panel">
          <div className="panel-title">AI grading</div>
          <div className="panel-body">
            {grading?.criteria_scores?.map((c) => (
              <div key={c.criterion_id} className="criterion-block">
                <div className="criterion-header">
                  <span className="criterion-id">{c.criterion_id}</span>
                  <ScoreChip awarded={c.marks_awarded} max={c.max_marks} />
                </div>
                <p className="criterion-justification">{c.justification}</p>
                {c.cited_chunk_id ? (
                  <span className="citation-tag">→ {c.cited_chunk_id}</span>
                ) : (
                  <span className="citation-tag citation-none">no citation</span>
                )}
              </div>
            ))}

            {grading?.self_check_notes && (
              <div className="self-check-note">
                <span className="self-check-label">Self-check</span>
                <p>{grading.self_check_notes}</p>
                <span className={`confidence-tag confidence-${grading.self_reported_confidence}`}>
                  {grading.self_reported_confidence} confidence
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="detail-panel">
          <div className="panel-title">Retrieved evidence</div>
          <div className="panel-body">
            {submission.retrieved_chunks?.length ? (
              submission.retrieved_chunks.map((chunk) => (
                <div key={chunk.chunk_id} className="evidence-block">
                  <div className="evidence-header">
                    <span className="mono evidence-id">{chunk.chunk_id}</span>
                    <span className="mono evidence-similarity">{chunk.similarity?.toFixed(3)}</span>
                  </div>
                  <div className="evidence-section">{chunk.section}</div>
                  <p className="evidence-text">{chunk.text}</p>
                </div>
              ))
            ) : (
              <p className="panel-empty">No retrieved chunks recorded.</p>
            )}
          </div>
        </div>
      </div>

      <div className="review-bar">
        {alreadyReviewed ? (
          <div className="review-done">
            <span className={`status-pill ${submission.ta_status}`}>
              {submission.ta_status === 'accepted' ? 'Accepted' : `Overridden → ${submission.ta_override_score}`}
            </span>
            {submission.ta_notes && <span className="review-notes">"{submission.ta_notes}"</span>}
          </div>
        ) : showOverrideForm ? (
          <div className="override-form">
            <input
              type="number"
              step="0.5"
              placeholder="Override score"
              value={overrideScore}
              onChange={(e) => setOverrideScore(e.target.value)}
              className="override-input"
            />
            <input
              type="text"
              placeholder="Notes (optional)"
              value={overrideNotes}
              onChange={(e) => setOverrideNotes(e.target.value)}
              className="override-input override-notes"
            />
            <button className="btn btn-primary" onClick={handleOverrideSubmit} disabled={submitting}>
              {submitting ? 'Submitting…' : 'Submit override'}
            </button>
            <button className="btn" onClick={() => setShowOverrideForm(false)} disabled={submitting}>Cancel</button>
          </div>
        ) : (
          <>
            <button className="btn btn-primary" onClick={handleAccept} disabled={submitting}>
              {submitting ? 'Submitting…' : 'Accept AI grade'}
            </button>
            <button className="btn" onClick={() => setShowOverrideForm(true)} disabled={submitting}>
              Override score
            </button>
          </>
        )}
      </div>
    </div>
  )
}