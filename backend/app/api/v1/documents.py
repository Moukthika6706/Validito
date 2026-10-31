from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.ingestion.storage import absolute_path

from app.api.deps import DB, CurrentUser
from app.models import DocumentStatus, DocumentType, User
from app.schemas.common import Page
from app.schemas.document import BulkUploadResult, DocumentDetail, DocumentLink, DocumentOut, DocumentStatusOut, DocumentTextOut, EntityOut, PagesOut
from app.services import render_service
from app.audit import events, record
from app.services import document_service as svc

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentOut,
    status_code=202,
    summary="Upload a term sheet (PDF, DOCX, PNG, JPG, TIFF) and queue it for processing",
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[DocumentType, Form()] = DocumentType.term_sheet,
    rule_pack_key: Annotated[str | None, Form(max_length=32, pattern=r"^[a-z0-9_\-]*$")] = None,
    related_document_id: Annotated[int | None, Form()] = None,
    user: User = CurrentUser,
    db: Session = DB,
):
    content = await file.read()
    return svc.create_document(
        db,
        owner=user,
        filename=file.filename or "upload",
        content=content,
        doc_type=doc_type,
        rule_pack_key=rule_pack_key or None,
        related_document_id=related_document_id,
    )


@router.post(
    "/bulk",
    response_model=BulkUploadResult,
    status_code=202,
    summary="Upload several files at once; each is accepted or rejected independently",
)
async def bulk_upload(
    files: Annotated[list[UploadFile], File()],
    doc_type: Annotated[DocumentType, Form()] = DocumentType.term_sheet,
    rule_pack_key: Annotated[str | None, Form(max_length=32, pattern=r"^[a-z0-9_\-]*$")] = None,
    user: User = CurrentUser,
    db: Session = DB,
):
    payload = [(f.filename or "upload", await f.read()) for f in files]
    results = svc.create_documents_bulk(db, owner=user, files=payload, doc_type=doc_type, rule_pack_key=rule_pack_key or None)
    accepted = sum(1 for r in results if r["accepted"])
    return BulkUploadResult(accepted=accepted, rejected=len(results) - accepted, results=results)


@router.get("/status", response_model=list[DocumentStatusOut], summary="Poll-friendly status for a set of document ids")
def status_snapshot(
    ids: str = Query(..., description="Comma-separated document ids, max 200"),
    user: User = CurrentUser,
    db: Session = DB,
):
    parsed = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    return svc.status_snapshot(db, user, parsed)


@router.get("", response_model=Page[DocumentOut], summary="List documents visible to the caller")
def list_documents(
    status: DocumentStatus | None = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = CurrentUser,
    db: Session = DB,
):
    items, total = svc.list_documents(db, user, status_filter=status, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentDetail, summary="Document with extracted entities")
def get_document(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return svc.document_detail(db, document)


@router.get("/{document_id}/entities", response_model=list[EntityOut])
def get_entities(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return sorted(document.entities, key=lambda e: (e.entity_type, -e.confidence))


@router.get("/{document_id}/text", response_model=DocumentTextOut, summary="Extracted raw text")
def get_text(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return DocumentTextOut(id=document.id, raw_text=document.raw_text, page_count=document.page_count, ocr_used=document.ocr_used)


@router.get("/{document_id}/file", summary="Download / render the original upload")
def get_file(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return FileResponse(absolute_path(document.storage_path), media_type=document.mime_type, filename=document.original_filename,
                        content_disposition_type="inline")


@router.get("/{document_id}/pages", response_model=PagesOut, summary="Page geometry and whether the original can be rendered")
def pages(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return render_service.pages_info(document)


@router.get(
    "/{document_id}/pages/{number}.png",
    summary="Render one page as PNG (for the review overlay)",
    responses={200: {"content": {"image/png": {}}}, 404: {"description": "No such page, or the file type cannot be rendered"}},
)
def page_png(document_id: int, number: int, dpi: int = Query(render_service.DEFAULT_DPI, ge=36, le=render_service.MAX_DPI), user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    png = render_service.render_page_png(document, number, dpi)
    if number == 1:
        # One event per document view rather than per page keeps the trail readable.
        record(db, event_type=events.DOCUMENT_RENDERED, target_type="document", target_id=document.id, document_id=document.id,
               actor_id=user.id, payload={"dpi": dpi, "source": render_service.render_source(document)[0]})
        db.commit()
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=202, summary="Re-run extraction + validation")
def reprocess(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return svc.reprocess_document(db, document, user)


@router.put("/{document_id}/link", response_model=DocumentOut, summary="Link a related document for cross-document checks")
def link(document_id: int, body: DocumentLink, user: User = CurrentUser, db: Session = DB):
    document = svc.get_document_or_404(db, document_id, user)
    return svc.link_documents(db, document, body.related_document_id, user)
