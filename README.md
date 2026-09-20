# Validito

**AI-powered term sheet validation with explainable flags, confidence-based routing and an immutable audit trail.**

Validito ingests ISDA / LMA-style term sheets (PDF, DOCX, scanned images), extracts the key
clauses with OCR + NER, validates them against pluggable regulatory rule packs and a
scikit-learn anomaly detector, explains every flag it raises, and routes only the ambiguous
cases to a human reviewer — while recording every decision in a hash-chained audit log.

```
upload ─▶ extract (OCR + NER) ─▶ rule engine ─▶ ML anomaly ─▶ explain ─▶ route ─┬─▶ auto-approved
                                    │                                            └─▶ review queue ─▶ reviewer accepts / rejects / overrides
                                    └────────────── every step appended to the audit log ─────────────────────────────┘
```

---

## Quick start (Docker)

```bash
git clone https://github.com/Moukthika6706/Validito.git
cd Validito
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:5173 | React UI |
| http://localhost:5173/docs | Swagger / OpenAPI (proxied to the API) |
| http://localhost:8000/health | API health |

The API container runs migrations, seeds the rule packs, three demo accounts and four
processed sample documents on first boot.

| Account | Password | Role |
|---|---|---|
| `admin@validito.demo` | `Validito123!` | admin — everything + rule packs + users |
| `reviewer@validito.demo` | `Validito123!` | reviewer — review queue, all documents |
| `analyst@validito.demo` | `Validito123!` | analyst — own uploads only |

> First build downloads CPU PyTorch + EasyOCR models (~1 GB) so scanned documents work out of the box.
> Set `SEED_DEMO_DATA=false` in the environment to boot with an empty database.

## Quick start (local, no Docker)

Backend (Python 3.12):

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt                       # add --extra-index-url https://download.pytorch.org/whl/cpu for CPU-only torch
python -m spacy download en_core_web_sm
cp ../.env.example .env                               # then edit MYSQL_* / REDIS_URL
alembic upgrade head
python scripts/make_samples.py                        # demo term sheets into ../samples
python scripts/seed.py --samples                      # demo users, rule packs, processed samples
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker -Q extraction,validation,default --loglevel=info
```

No MySQL / Redis to hand? Put this in `backend/.env` and everything runs in-process on SQLite:

```
DATABASE_URL=sqlite:///./dev.db
CELERY_TASK_ALWAYS_EAGER=true
```

Frontend (Node 20):

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :8000
```

Tests:

```bash
cd backend && python -m pytest -q      # 83 tests: normalisers, extraction, rule engine, ML, routing, pipeline, API
```

---

## How it works (pitch version)

1. **Ingest.** Analysts upload a PDF, DOCX or scan. The API validates the file (MIME sniffing,
   size, extension allow-list), stores it content-addressed, writes an audit event and returns
   `202` immediately — processing runs on Celery workers that scale independently of the API.

2. **Extract.** PyMuPDF pulls the text layer; pages without one are rendered and passed
   through EasyOCR. A label-driven extractor reads the "Label: Value" structure of a term
   sheet for 20 fields (notional, dates, parties, rates, governing law, settlement, day count …),
   normalising each value (`USD 50,000,000` → `{amount: 5e7, currency: USD}`,
   `3-month SOFR + 45 bps` → `{benchmark: SOFR, spread_bps: 45}`). A rule-augmented spaCy NER
   pass adds recall on free-text sheets. Every entity carries a confidence that is scaled down
   on OCR'd pages.

3. **Validate.** The rule engine runs the document's rule pack — YAML files describing ISDA and
   LMA conventions with a small vocabulary of check types (`presence`, `range`, `date_order`,
   `forbidden_values`, `cross_doc_equal`, …). Adding a market means adding a YAML file; adding a
   kind of check means registering one Python function. Linked documents (term sheet ↔
   confirmation) are compared field by field. An Isolation Forest scores the overall
   combination of terms against what the pack normally sees.

4. **Explain.** Every flag stores *which rule or model feature fired*, *a rendered
   human-readable explanation*, *the evidence values*, *a frozen snapshot of the rule as it was*,
   and *a confidence* = rule certainty × extraction quality × reviewer-feedback calibration. ML
   flags list the top deviating features with z-scores ("fixed rate 18.5% vs typical 3.6%,
   8.3σ above"). Nothing is a black box.

5. **Route.** A pure policy function decides: blocking severities or any non-trivial flag
   below the confidence threshold → review queue; otherwise auto-approve. The threshold and
   severities live in the rule pack. The dashboard reports **% auto-approved / manual review
   reduction** from `GET /api/v1/metrics/summary`.

6. **Review.** Reviewers see the extracted clause side by side with the rule that fired, the
   evidence and the confidence, and accept / reject / override with a comment. Rejections feed
   back: a rule reviewers keep rejecting loses confidence and drifts into the "ask a human"
   band instead of blocking approvals.

7. **Audit.** Every extraction, flag, routing decision, rule-pack edit and reviewer action is
   an append-only row whose hash covers the previous row. `GET /api/v1/audit?document_id=X`
   answers "show me every decision on document X"; `GET /api/v1/audit/verify` proves nothing
   was altered.

---

## Architecture

```
frontend/ (React + Vite)  ──▶  nginx  ──▶  backend/app/api/v1 (FastAPI, JWT)
                                                │
                                   Redis broker │ Celery chain: extract → validate
                                                ▼
        ┌────────────────┬──────────────────┬────────────────┬──────────────────┐
        │ ingestion/     │ extraction/      │ rules/         │ ml/              │
        │ validate+store │ PyMuPDF, EasyOCR │ YAML packs +   │ features,        │
        │                │ spaCy, normalise │ check registry │ IsolationForest, │
        │                │                  │ + engine       │ feedback calib.  │
        └────────────────┴──────────────────┴────────────────┴──────────────────┘
                                                │
                       validation/ (orchestrator + routing) · explainability/ · audit/
                                                ▼
                                             MySQL
```

| Directory | Responsibility |
|---|---|
| `backend/app/api/v1` | Versioned REST routers (auth, documents, validation, review, audit, rule-packs, metrics, users) |
| `backend/app/services` | Business logic shared by routers and workers |
| `backend/app/ingestion` | Upload validation, MIME sniffing, content-addressed storage |
| `backend/app/extraction` | Text extraction, OCR, field specs, normalisers, NER, extraction stage |
| `backend/app/rules` | Rule-pack schema, loader, check registry, engine, `packs/isda.yaml`, `packs/lma.yaml` |
| `backend/app/ml` | Feature engineering, anomaly model, reviewer-feedback calibration |
| `backend/app/validation` | Validation orchestrator and routing policy |
| `backend/app/explainability` | Confidence bands, source descriptions, document-level summary |
| `backend/app/audit` | Hash-chained append-only logger and verifier |
| `backend/app/workers` | Celery app (per-stage queues) and tasks |
| `backend/app/models` | SQLAlchemy ORM; `backend/alembic` migrations |
| `frontend/src/pages` | Dashboard, Documents, Upload, DocumentDetail, ReviewQueue, ReviewDocument, AuditTrail, AdminRulePacks, AdminUsers |
| `docs/` | `DATA_MODEL.md`, `ARCHITECTURE.md` |
| `samples/` | Demo term sheets (clean / faulty ISDA, confirmation, LMA DOCX, scanned PNG) |

**Why FastAPI over Flask:** auto-generated OpenAPI docs and Pydantic request validation were
explicit requirements and are native to FastAPI; Flask needs extensions for both. Heavy OCR/ML
work runs in Celery regardless, so async request handling is a secondary benefit.

**Scaling:** extraction (OCR-heavy) and validation (CPU-light) are separate Celery tasks on
separate queues, so `docker compose up --scale worker=N` — or dedicated GPU workers with
`-Q extraction` — scale the expensive stage on its own. The API is stateless (JWT) and can be
replicated behind the nginx proxy.

## Data model

See [docs/DATA_MODEL.md](docs/DATA_MODEL.md). In one line: `users` → `documents` → `extracted_entities`;
`validation_runs` → `flags` (rule id, snapshot, explanation, evidence, confidence) → `review_actions`;
`rule_packs` (versioned JSON); `audit_log` (hash-chained). Every flag column after `source` exists so
a reviewer can understand it without reading code.

## API overview

All routes are under `/api/v1` and require `Authorization: Bearer <jwt>` except register/login.
Full interactive docs at `/docs`.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Documents | `POST /documents` (upload, 202), `GET /documents`, `GET /documents/{id}`, `/text`, `/entities`, `/flags`, `/runs`, `POST /{id}/reprocess`, `POST /{id}/validate`, `PUT /{id}/link` |
| Validation | `GET /validation/runs/{id}`, `GET /flags/{id}` |
| Review (reviewer+) | `GET /review/queue`, `POST /review/flags/{id}/actions`, `POST /review/documents/{id}/complete` |
| Audit | `GET /audit`, `GET /audit/documents/{id}`, `GET /audit/event-types`, `GET /audit/verify` (admin) |
| Rule packs | `GET /rule-packs`, `GET /rule-packs/{key}`, `GET /rule-packs/checks`; admin: `POST /rule-packs`, `PATCH /rule-packs/{key}/rules/{rule_id}`, `POST /rule-packs/versions/{id}/activate` |
| Metrics | `GET /metrics/summary` — auto-approval %, manual review reduction, flag mix, top rules, daily series |
| Users (admin) | `GET /users`, `POST /users`, `PATCH /users/{id}` |

## Adding a rule or a rule pack

```yaml
# backend/app/rules/packs/isda.yaml
- id: isda.spread.range
  check: range                       # any name registered in app/rules/checks
  field: interest_rate
  params: {path: spread_bps, min: -200, max: 1000}
  severity: warning
  confidence: 0.75
  title: Spread off-market
  explanation: A spread of {value} bps is outside the {min} to {max} bps range expected over the benchmark.
```

A new pack is a new YAML file with its own `key`; it is seeded on the next boot and selectable at
upload (or auto-detected from its `applies_to` keywords). Admins can also edit rules from the UI —
each edit cuts a new pack version, and flags keep the snapshot of the version that raised them.

## Security notes

- JWT (HS256) with bcrypt password hashing; every protected route resolves the user from the token.
- Role guards: analysts only see their own documents (other ids return 404 to prevent enumeration);
  reviewers see all documents and the queue; admins additionally manage rule packs and users.
- Uploads: extension allow-list, MIME sniffed from content (DOCX verified as a real Word zip), size
  limit, filename sanitisation, storage paths validated against the storage root.
- All DB access goes through SQLAlchemy parameters — no string-built SQL.
- Audit log is append-only in code and tamper-evident through the hash chain.

## Configuration

See [`.env.example`](.env.example). Key settings: `DATABASE_URL` (or `MYSQL_*`), `REDIS_URL`,
`SECRET_KEY`, `STORAGE_DIR`, `MAX_UPLOAD_MB`, `OCR_USE_GPU`, `CELERY_TASK_ALWAYS_EAGER`
(run the pipeline inline — handy for dev/tests), `AUTO_APPROVE_CONFIDENCE` (default; packs override).
