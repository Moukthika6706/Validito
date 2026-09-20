# Validito

AI-powered term sheet validation for ISDA / LMA-style financial documents.

Validito ingests term sheets (PDF, scanned images, DOCX), extracts key clauses with OCR + NER,
validates them against pluggable regulatory rule packs and an ML anomaly layer, explains every
flag it raises, and routes only ambiguous cases to human reviewers — with an immutable audit trail.

> Status: under active development for the Barclays fintech hackathon. See `docs/` for the
> architecture and data model; setup instructions will land in this README as milestones ship.

## Repository layout

```
backend/     FastAPI API, Celery workers, extraction / rules / ML pipeline
frontend/    React (Vite) dashboard
docs/        Architecture and data model
samples/     Demo term sheets
```

## Roadmap

1. Ingestion + extraction (OCR, spaCy NER)
2. Rule engine + ISDA / LMA rule packs
3. ML anomaly detection, explainability, confidence-based routing
4. Versioned REST API with OpenAPI docs
5. JWT auth, roles, scoped access
6. React dashboard
7. Docker Compose deployment
