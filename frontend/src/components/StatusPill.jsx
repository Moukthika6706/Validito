import { humanize } from '../utils/format'

const DOC_TONE = {
  queued: 'neutral',
  extracting: 'neutral',
  extracted: 'neutral',
  validating: 'neutral',
  auto_approved: 'ok',
  needs_review: 'warn',
  reviewed: 'info',
  failed: 'bad',
}
const SEV_TONE = { info: 'neutral', warning: 'warn', error: 'bad', critical: 'crit' }
const FLAG_TONE = { open: 'warn', accepted: 'bad', rejected: 'ok', overridden: 'info', superseded: 'neutral' }
const FLAG_LABEL = { accepted: 'Confirmed', rejected: 'False positive', overridden: 'Overridden' }
const PROCESSING = new Set(['queued', 'extracting', 'extracted', 'validating'])

export function StatusPill({ status, outcome }) {
  let tone = DOC_TONE[status] || 'neutral'
  let label = humanize(status)
  if (status === 'reviewed' && outcome) {
    tone = outcome === 'approved' ? 'ok' : 'bad'
    label = `Reviewed · ${outcome}`
  }
  if (PROCESSING.has(status)) label = { queued: 'Queued', extracting: 'Extracting', extracted: 'Extracted', validating: 'Validating' }[status]
  return <span className={`pill pill-${tone} ${PROCESSING.has(status) ? 'pill-processing' : ''}`}>{label}</span>
}

export function SeverityPill({ severity }) {
  return <span className={`pill pill-${SEV_TONE[severity] || 'neutral'}`}>{severity}</span>
}

export function FlagStatusPill({ status }) {
  return <span className={`pill pill-${FLAG_TONE[status] || 'neutral'}`}>{FLAG_LABEL[status] || humanize(status)}</span>
}

export function SourcePill({ source }) {
  const label = { rule: 'Rule', ml: 'ML anomaly', cross_doc: 'Cross-doc' }[source] || source
  return <span className="pill pill-plain">{label}</span>
}

export function AIProposedPill() {
  return (
    <span className="pill pill-info" title="Proposed by the LLM fallback because no deterministic extractor found this field. The value was verified to appear in the document text, but a human must confirm it.">
      AI-proposed
    </span>
  )
}

export function RolePill({ role }) {
  return <span className="pill pill-plain">{role}</span>
}
