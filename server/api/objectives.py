"""Objectives — overarching, direction-setting goals (bigger than a Task).

Where Tasks are concrete to-dos, an Objective steers the whole adventure
("Gather a party of five", "Defeat the Demon Queen before the next Blood Moon").
They're injected into the narrator prompt so the story bends toward them.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.schemas import ObjectiveCreate, ObjectiveSchema, ObjectiveUpdate
from server.db.database import get_session
from server.db.models import Objective

router = APIRouter()


def _to_schema(obj: Objective) -> ObjectiveSchema:
    return ObjectiveSchema(id=obj.id, text=obj.text, status=obj.status, detail=obj.detail)


@router.get("/objectives", response_model=list[ObjectiveSchema])
async def list_objectives(session: AsyncSession = Depends(get_session)):
    objs = (await session.execute(select(Objective).order_by(Objective.sort_order))).scalars().all()
    return [_to_schema(o) for o in objs]


@router.post("/objectives", response_model=ObjectiveSchema, status_code=201)
async def create_objective(
    data: ObjectiveCreate,
    session: AsyncSession = Depends(get_session),
):
    max_order = (await session.execute(
        select(func.coalesce(func.max(Objective.sort_order), -1))
    )).scalar()
    obj = Objective(
        text=data.text,
        status=data.status,
        detail=data.detail,
        sort_order=(max_order or 0) + 1,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return _to_schema(obj)


@router.put("/objectives/{objective_id}", response_model=ObjectiveSchema)
async def update_objective(
    objective_id: str,
    data: ObjectiveUpdate,
    session: AsyncSession = Depends(get_session),
):
    obj = await session.get(Objective, objective_id)
    if not obj:
        raise HTTPException(404, "Objective not found")
    if data.text is not None:
        obj.text = data.text
    if data.status is not None:
        obj.status = data.status
    if data.detail is not None:
        obj.detail = data.detail
    await session.commit()
    await session.refresh(obj)
    return _to_schema(obj)


@router.delete("/objectives/{objective_id}", status_code=204)
async def delete_objective(
    objective_id: str,
    session: AsyncSession = Depends(get_session),
):
    obj = await session.get(Objective, objective_id)
    if not obj:
        raise HTTPException(404, "Objective not found")
    await session.delete(obj)
    await session.commit()
