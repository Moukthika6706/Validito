# Data model

MySQL via SQLAlchemy 2.0; schema managed with Alembic.

| Table | Purpose | Key columns |
|---|---|---|
| `users` | accounts + roles | `id, email (unique), password_hash, full_name, role {analyst, reviewer, admin}, is_active, created_at` |
| `documents` | one row per upload | `id, owner_id→users, original_filename, storage_path, mime_type, size_bytes, sha256, doc_type {term_sheet, confirmation, other}, rule_pack_key, status, failed_stage {extracting, validating}, attempts, related_document_id→documents, amendment_of_id→documents, amended_fields (JSON list of entity types), raw_text, ocr_used, error_message, review_outcome, claimed_by_id→users, claimed_at, created_at, updated_at` |
| `extracted_entities` | NER / regex output | `id, document_id, entity_type, raw_text, normalized_value (JSON), confidence, extractor {spacy_ner, entity_ruler, regex, llm}, page, char_start, char_end, bbox (JSON)` — `bbox` is a list of `{page, x0, y0, x1, y1}` rectangles as fractions of the page size (PyMuPDF search for text PDFs, EasyOCR line boxes for scans; null for DOCX) |
| `rule_packs` | versioned ISDA / LMA configs | `id, key, name, version, description, config (JSON), is_active, created_by, created_at` — `(key, version)` unique |
| `validation_runs` | one pipeline execution | `id, document_id, rule_pack_id, ml_model_version, status, overall_score, routing_decision {auto_approved, needs_review}, routing_reason, started_at, completed_at` |
| `flags` | explainable findings | `id, validation_run_id, document_id, entity_id (nullable), source {rule, ml, cross_doc}, rule_id, rule_snapshot (JSON), severity {info, warning, error, critical}, confidence, title, explanation, evidence (JSON), status {open, accepted, rejected, overridden}` |
| `review_actions` | human decisions | `id, flag_id, reviewer_id, action {accept, reject, override}, comment, override_value (JSON), created_at` |
| `audit_chain_head` | single row (id=1) holding the newest audit hash; locked FOR UPDATE by every writer so concurrent recorders cannot fork the chain | `id, last_hash, last_entry_id` |
| `audit_log` | append-only, hash-chained | `id, document_id (nullable), actor_id (nullable = system), event_type, target_type, target_id, payload (JSON), created_at, prev_hash, hash` |

## Explainability is first-class

Every `flags` row carries:

- `rule_id` / `source` — which rule or ML feature fired
- `rule_snapshot` — the rule definition as it was at the time (audit-safe even if the pack changes later)
- `explanation` — human-readable text rendered from the rule's template
- `evidence` — the concrete values / features that triggered the flag
- `confidence` — calibrated score used for routing

## Document lifecycle

```
queued → extracting → extracted → validating → auto_approved | needs_review → reviewed
            └──────────────────────────┴──────→ failed  (failed_stage records which stage)
```

`queued` is set on upload, `extracting` / `validating` by the Celery task that owns the stage,
and `extracted` between the two tasks. A stage retries transient errors with exponential backoff
(30s, 60s, 120s; max 3 retries) and only then marks the document `failed` with `failed_stage`,
`error_message` and the `attempts` count. `POST /documents/{id}/reprocess` resets these and
re-queues. Terminal statuses: `auto_approved`, `needs_review`, `reviewed`, `failed`.

### Review claims

`claimed_by_id` / `claimed_at` form a soft lock that expires after `REVIEW_CLAIM_TTL_MINUTES`
(default 30). Reviewer writes auto-claim a free document and return `409` with the holder's name
and expiry when another reviewer holds it; completing the review releases the claim.

## Routing

A pure function of the flags produced by a validation run. A document auto-approves when no
open flag has `severity >= warning` with `confidence >= auto_approve_threshold`; otherwise it
enters the review queue. Thresholds live in the rule pack so they can be tuned per market.

## Audit immutability

`audit_log` has no update / delete path in the ORM. Each row stores `prev_hash` and its own
`hash = sha256(prev_hash + canonical(payload) + created_at)`, so the chain can be verified.

## Feedback loop

`review_actions` is the training signal: a rejected flag is a false positive for that
`rule_id` / ML feature, an accepted flag a true positive. The ML training script reads this
table to re-weight features and adjust per-rule confidence calibration.
