from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.finding import Finding
from app.models.remediation import RemediationTicket, RemediationStatus
from app.schemas.remediation import (
    RemediationTicketCreate,
    RemediationTicketUpdate,
    RemediationTicketResponse,
    RemediationTicketListResponse,
)

router = APIRouter(prefix="/projects/{project_id}/remediation", tags=["Remediation"])


@router.post("/", response_model=RemediationTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_remediation_ticket(
    project_id: int,
    ticket_data: RemediationTicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new remediation ticket for a finding."""
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Verify finding exists
    result = await db.execute(
        select(Finding).where(Finding.id == ticket_data.finding_id, Finding.project_id == project_id)
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    
    # Check if ticket already exists for this finding
    result = await db.execute(
        select(RemediationTicket).where(RemediationTicket.finding_id == ticket_data.finding_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Remediation ticket already exists for this finding")
    
    # Create ticket
    ticket = RemediationTicket(
        finding_id=ticket_data.finding_id,
        project_id=project_id,
        title=ticket_data.title,
        description=ticket_data.description,
        remediation_plan=ticket_data.remediation_plan or finding.remediation_suggestion,
        priority=ticket_data.priority,
        assigned_to=ticket_data.assigned_to,
        assigned_by=current_user.id,
        due_date=ticket_data.due_date,
        status=RemediationStatus.OPEN,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    
    return ticket


@router.get("/", response_model=List[RemediationTicketListResponse])
async def list_remediation_tickets(
    project_id: int,
    status_filter: Optional[RemediationStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all remediation tickets for a project."""
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    
    query = select(RemediationTicket).where(RemediationTicket.project_id == project_id)
    if status_filter:
        query = query.where(RemediationTicket.status == status_filter)
    
    result = await db.execute(query.order_by(RemediationTicket.created_at.desc()))
    tickets = result.scalars().all()
    
    return tickets


@router.get("/{ticket_id}", response_model=RemediationTicketResponse)
async def get_remediation_ticket(
    project_id: int,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific remediation ticket."""
    result = await db.execute(
        select(RemediationTicket).where(
            RemediationTicket.id == ticket_id,
            RemediationTicket.project_id == project_id
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return ticket


@router.put("/{ticket_id}", response_model=RemediationTicketResponse)
async def update_remediation_ticket(
    project_id: int,
    ticket_id: int,
    ticket_data: RemediationTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a remediation ticket."""
    result = await db.execute(
        select(RemediationTicket).where(
            RemediationTicket.id == ticket_id,
            RemediationTicket.project_id == project_id
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Update fields
    if ticket_data.status is not None:
        ticket.status = ticket_data.status
        if ticket_data.status == RemediationStatus.RESOLVED:
            ticket.resolved_at = datetime.utcnow()
        elif ticket_data.status == RemediationStatus.VERIFIED:
            ticket.verified_at = datetime.utcnow()
    
    if ticket_data.assigned_to is not None:
        ticket.assigned_to = ticket_data.assigned_to
    if ticket_data.resolution_notes is not None:
        ticket.resolution_notes = ticket_data.resolution_notes
    if ticket_data.due_date is not None:
        ticket.due_date = ticket_data.due_date
    
    await db.commit()
    await db.refresh(ticket)
    
    return ticket


@router.post("/{ticket_id}/verify", response_model=RemediationTicketResponse)
async def verify_remediation(
    project_id: int,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify that a remediation has been completed successfully."""
    result = await db.execute(
        select(RemediationTicket).where(
            RemediationTicket.id == ticket_id,
            RemediationTicket.project_id == project_id
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status != RemediationStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Ticket must be in RESOLVED status to verify")
    
    ticket.status = RemediationStatus.VERIFIED
    ticket.verified_at = datetime.utcnow()
    
    # Update finding status
    finding_result = await db.execute(
        select(Finding).where(Finding.id == ticket.finding_id)
    )
    finding = finding_result.scalar_one_or_none()
    if finding:
        finding.status = "resolved"
    
    await db.commit()
    await db.refresh(ticket)
    
    return ticket
