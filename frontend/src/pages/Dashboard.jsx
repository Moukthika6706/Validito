import { Link, useNavigate } from 'react-router-dom'
import { documents, metrics } from '../api/endpoints'
import Button from '../components/Button'
import GlowBackground from '../components/GlowBackground'
import StatCard from '../components/StatCard'
import { StatusPill } from '../components/StatusPill'
import { ErrorState, SkeletonRows } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtRelative } from '../utils/format'

const IN_FLIGHT = new Set(['uploaded', 'processing', 'extracted', 'validated'])

export default function Dashboard() {
  const { user, isReviewer } = useAuth()
  const navigate = useNavigate()
  const m = useAsync(() => metrics.summary({ days: 14 }), [], { interval: 20000 })
  const recent = useAsync(() => documents.list({ limit: 10 }), [], {
    interval: 4000,
    shouldPoll: (d) => !d || d.items.some((x) => IN_FLIGHT.has(x.status)),
  })
  const hasDocs = (recent.data?.total ?? 0) > 0

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">{isReviewer ? 'Team overview' : `Welcome back, ${user.full_name.split(' ')[0]}`}</p>
          <h1 className="display display-h1">
            Your validation queue
            <br />
            at a glance
          </h1>
        </div>
        <div className="row">
          {isReviewer && (
            <Button variant="secondary" to="/queue">
              Open review queue
            </Button>
          )}
          <Button to="/upload">Upload term sheet</Button>
        </div>
      </div>

      <section style={{ position: 'relative', marginBottom: 56 }}>
        <GlowBackground position="behind" />
        {m.error ? (
          <ErrorState error={m.error} onRetry={m.reload} title="Stats unavailable" />
        ) : (
          <StatRow data={m.data} loading={m.loading && !m.data} />
        )}
      </section>

      {hasDocs ? (
        <section>
          <div className="spread" style={{ marginBottom: 16 }}>
            <h2 className="display display-h2">Recent activity</h2>
            {recent.data?.total > 10 && (
              <Link to="/queue" className="small muted">
                {isReviewer ? 'View the full queue' : ''}
              </Link>
            )}
          </div>
          <div className="activity">
            {recent.data.items.map((d) => (
              <Link key={d.id} className="activity-row" to={`/review/${d.id}`}>
                <div>
                  <div className="activity-name">{d.original_filename}</div>
                  <div className="activity-meta">
                    {d.doc_type.replace('_', ' ')} · {d.rule_pack_key ? d.rule_pack_key.toUpperCase() : 'auto-detect'}
                    {d.ocr_used ? ' · OCR' : ''}
                  </div>
                </div>
                <div className="activity-meta">{fmtRelative(d.created_at)}</div>
                <div>
                  <StatusPill status={d.status} outcome={d.review_outcome} />
                </div>
                <div className="chev">›</div>
              </Link>
            ))}
          </div>
        </section>
      ) : recent.loading && !recent.data ? (
        <SkeletonRows n={3} />
      ) : recent.error ? (
        <ErrorState error={recent.error} onRetry={recent.reload} />
      ) : (
        <HowItWorks onUpload={() => navigate('/upload')} />
      )}
    </div>
  )
}

function StatRow({ data, loading }) {
  const notional = data?.notional_validated || {}
  const topCcy = Object.entries(notional).sort((a, b) => b[1] - a[1])[0]
  const notionalText = topCcy ? compactMoney(topCcy[1]) : '0'
  const others = Object.keys(notional).length - 1
  return (
    <div className="stat-row">
      <StatCard loading={loading} value={data ? data.auto_approved_pct.toFixed(0) : ''} unit="%" label="Auto-approval rate" hint={data ? `${data.auto_approved_total} of ${data.decided_total} cleared without a human` : ' '} />
      <StatCard loading={loading} value={data?.flagged_this_week ?? ''} label="Flagged this week" hint={data ? `${data.decided_this_week} decided in the last 7 days` : ' '} />
      <StatCard loading={loading} value={notionalText} unit={topCcy?.[0]} label="Notional validated" hint={others > 0 ? `plus ${others} other currenc${others === 1 ? 'y' : 'ies'}` : 'across decided documents'} />
      <StatCard loading={loading} value={data?.active_rule_packs ?? ''} label="Active rule packs" hint="ISDA · LMA" />
    </div>
  )
}

function compactMoney(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}bn`
  if (n >= 1e6) return `${(n / 1e6).toFixed(0)}m`
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`
  return String(Math.round(n))
}

const STEPS = [
  { n: '01', title: 'Upload', body: 'Drop a PDF, DOCX or scan. Processing starts in the background straight away.' },
  { n: '02', title: 'AI extracts', body: 'OCR and NER pull out notional, dates, parties, rates, governing law and more.' },
  { n: '03', title: 'Review flags', body: 'Rule packs and an anomaly model raise flags — each one explained, with a confidence.' },
  { n: '04', title: 'Approve or escalate', body: 'Clean documents auto-approve. Only ambiguous ones reach a reviewer.' },
]

function HowItWorks({ onUpload }) {
  return (
    <section className="how" style={{ position: 'relative' }}>
      <div>
        <p className="eyebrow">How it works</p>
        <h2 className="display display-h1" style={{ marginBottom: 20 }}>
          Nothing to review yet
        </h2>
        <div className="how-steps">
          {STEPS.map((s) => (
            <div className="how-step" key={s.n}>
              <div className="how-num">{s.n}</div>
              <div>
                <strong>{s.title}</strong>
                <span>{s.body}</span>
              </div>
            </div>
          ))}
        </div>
        <Button size="lg" onClick={onUpload} style={{ marginTop: 24 }}>
          Upload your first term sheet
        </Button>
      </div>
      <div className="how-visual">
        <GlowBackground position="right" soft />
        <div className="mock above">
          <div className="card card-tight">
            <div className="spread">
              <div>
                <div style={{ fontWeight: 600 }}>isda_irs_clean.pdf</div>
                <div className="micro muted">18 terms extracted</div>
              </div>
              <StatusPill status="auto_approved" />
            </div>
          </div>
          <div className="card card-tight">
            <div className="spread">
              <div>
                <div style={{ fontWeight: 600 }}>isda_irs_faulty.pdf</div>
                <div className="micro muted">9 flags · lowest confidence 50%</div>
              </div>
              <StatusPill status="needs_review" />
            </div>
          </div>
          <div className="card card-tight">
            <div className="spread">
              <div>
                <div style={{ fontWeight: 600 }}>lma_term_loan.docx</div>
                <div className="micro muted">running rule pack LMA</div>
              </div>
              <StatusPill status="processing" />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
