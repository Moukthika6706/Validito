from fastapi import APIRouter

from app.api.v1 import audit, auth, documents, metrics, review, rule_packs, users, validation

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(validation.router)
api_router.include_router(review.router)
api_router.include_router(audit.router)
api_router.include_router(rule_packs.router)
api_router.include_router(metrics.router)
api_router.include_router(users.router)
