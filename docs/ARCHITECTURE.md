# Architecture

```
            +------------+      +--------------+      +------------+
  upload -->|  FastAPI   |----->|    Redis     |----->|   Celery   |
            |  (api/v1)  |      |  (broker)    |      |  workers   |
            +-----+------+      +--------------+      +-----+------+
                  |                                         |
                  |            extract -> validate -> route (chained tasks)
                  v                                         v
            +------------+                           +--------------+
            |   MySQL    |<--------------------------|  pipeline    |
            |            |  entities, flags, audit   |  modules     |
            +------------+                           +--------------+
```

## Backend modules (`backend/app/`)

| Module | Responsibility |
|---|---|
| `ingestion/` | upload validation (size, MIME sniffing, extension allowlist), content hashing, storage |
| `extraction/` | text extraction (PDF / DOCX), EasyOCR for scanned input, spaCy NER + entity ruler, value normalisers |
| `rules/` | YAML rule-pack loader, pluggable check registry, rule engine |
| `ml/` | feature engineering, scikit-learn anomaly detection, training script |
| `validation/` | orchestrates rules + ML + cross-document checks into flags and a routing decision |
| `explainability/` | explanation templating and confidence calibration |
| `audit/` | append-only, hash-chained audit logger |
| `workers/` | Celery app and task definitions — one task per pipeline stage |
| `api/v1/` | versioned REST routers; OpenAPI generated automatically |
| `services/` | business logic shared between routers and workers |

## Why FastAPI

Auto-generated OpenAPI docs and Pydantic request validation are both explicit requirements;
FastAPI provides both natively, whereas Flask needs extensions for each. Heavy OCR / ML work
runs in Celery regardless, so async request handling is a secondary benefit.

## Why the pipeline is split into separate tasks

Extraction (OCR-heavy, benefits from GPU), rule checking (CPU-light) and ML scoring (CPU-medium)
have different scaling profiles. Each stage is its own Celery task so worker pools can be sized
independently, and a failure in one stage is retried without re-running the others.

## Rule packs are data, not code

`rules/packs/*.yaml` declare rules using a small set of check types (`presence`, `format`,
`range`, `consistency`, `cross_doc`, ...). Adding a new market convention means adding a YAML
file; adding a new *kind* of check means registering one function in `rules/checks/`.
