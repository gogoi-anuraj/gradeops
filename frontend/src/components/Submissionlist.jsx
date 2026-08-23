import { useState } from 'react'
import { gradeSubmission } from '../api.js'

const STATUS_LABELS = {
  ungraded: 'Ungraded',
  graded: 'Needs review',
  accepted: 'Accepted',
  overridden: 'Overridden',
}

function formatScore(submission) {
  const grading = submission.final_grading
  if (submission.ta_status === 'overridden' && submission.ta_override_score != null) {
    const originalMax = grading ? grading.total_max : null
    return {
      primary: originalMax != null
        ? `${submission.ta_override_score}/${originalMax}`
        : `${submission.ta_override_score}`,
      original: grading ? `${grading.total_score}/${grading.total_max}` : null,
    }
  }
  if (!grading) return { primary: '—', original: null }
  return { primary: `${grading.total_score}/${grading.total_max}`, original: null }
}

export default function SubmissionList({ submissions, onSelect, onRefresh }) {
  const [gradingFilename, setGradingFilename] = useState(null)
  const [error, setError] = useState(null)

  async function handleGrade(filename) {
    setError(null)
    setGradingFilename(filename)
    try {
      await gradeSubmission(filename)
      await onRefresh()
    } catch (e) {
      setError(`Couldn't grade ${filename}: ${e.message}`)
    } finally {
      setGradingFilename(null)
    }
  }

  const flaggedCount = submissions.filter((s) => s.flagged_for_review).length
  const gradedCount = submissions.filter((s) => s.ta_status !== 'ungraded').length

  return (
    <div>
      <div className="list-summary">
        <span><strong>{submissions.length}</strong> submissions</span>
        <span><strong>{gradedCount}</strong> graded</span>
        <span><strong>{flaggedCount}</strong> flagged for review</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {submissions.length === 0 ? (
        <div className="empty-state">No submissions found. Check that transcriptions.json has entries.</div>
      ) : (
        <div className="submission-table">
          {submissions.map((s) => {
            const score = formatScore(s)
            return (
            <button
              key={s.filename}
              className="submission-row"
              onClick={() => s.ta_status !== 'ungraded' && onSelect(s.filename)}
            >
              <span className={`row-flag-strip ${s.flagged_for_review ? 'flagged' : ''}`} />

              <span className="row-filename">{s.filename}</span>

              <span className="row-question">
                <span className="q-label">{s.question_id || '—'}</span>
                {s.flagged_for_review && (
                  <span className="flag-note">{s.flag_reason || 'Flagged for review'}</span>
                )}
              </span>

              <span className={`status-pill ${s.ta_status}`}>
                {STATUS_LABELS[s.ta_status] || s.ta_status}
              </span>

              <span className="row-score">
                {score.primary}
                {score.original && (
                  <span className="row-score-original"> (was {score.original})</span>
                )}
              </span>

              <span className="row-action">
                {s.ta_status === 'ungraded' ? (
                  <button
                    className="btn btn-primary"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleGrade(s.filename)
                    }}
                    disabled={gradingFilename === s.filename}
                  >
                    {gradingFilename === s.filename ? 'Grading…' : 'Grade'}
                  </button>
                ) : (
                  <span className="btn" style={{ pointerEvents: 'none' }}>Review →</span>
                )}
              </span>
            </button>
            )
          })}
        </div>
      )}
    </div>
  )
}