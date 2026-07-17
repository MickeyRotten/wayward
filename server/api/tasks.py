"""Tasks — the flat to-do list (successor to quests + objectives)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.schemas import TaskCreate, TaskSchema, TaskUpdate
from server.db.database import get_session
from server.db.models import Task

router = APIRouter()


def _task_to_schema(task: Task) -> TaskSchema:
    return TaskSchema(id=task.id, text=task.text, status=task.status, notes=task.notes)


@router.get("/tasks", response_model=list[TaskSchema])
async def list_tasks(session: AsyncSession = Depends(get_session)):
    tasks = (await session.execute(select(Task).order_by(Task.sort_order))).scalars().all()
    return [_task_to_schema(t) for t in tasks]


@router.post("/tasks", response_model=TaskSchema, status_code=201)
async def create_task(
    data: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    max_order = (await session.execute(
        select(func.coalesce(func.max(Task.sort_order), -1))
    )).scalar()
    task = Task(
        text=data.text,
        status=data.status,
        notes=data.notes,
        sort_order=(max_order or 0) + 1,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return _task_to_schema(task)


@router.get("/tasks/{task_id}", response_model=TaskSchema)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return _task_to_schema(task)


@router.put("/tasks/{task_id}", response_model=TaskSchema)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if data.text is not None:
        task.text = data.text
    if data.status is not None:
        task.status = data.status
    if data.notes is not None:
        task.notes = data.notes
    await session.commit()
    await session.refresh(task)
    return _task_to_schema(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    await session.delete(task)
    await session.commit()
