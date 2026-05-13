import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, func, and_

from app.core.database import async_session_maker
from app.models.query_log import QueryLog


async def save_query_log(
    *,
    question: str,
    answer: str,
    agent_logs: Any,
    language: str = "ru",
    source: str = "api",
    ip_address: Optional[str] = None,
) -> Optional[str]:
    """Persist a successful query/answer pair. Returns the row id (str) or None on failure.

    Never raises — DB unavailability must not break the user response.
    """
    try:
        async with async_session_maker() as session:
            row = QueryLog(
                id=uuid.uuid4(),
                question=question or "",
                answer=answer or "",
                agent_logs=agent_logs,
                language=(language or "ru")[:8],
                source=(source or "api")[:32],
                ip_address=(ip_address or None),
            )
            session.add(row)
            await session.commit()
            return str(row.id)
    except Exception:
        return None


async def list_query_logs(
    *,
    page: int = 1,
    page_size: int = 20,
    source: Optional[str] = None,
    language: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """Return paginated list of query logs with simple filters.

    date_from / date_to are ISO date strings (YYYY-MM-DD); inclusive.
    """
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))

    conds = []
    if source:
        conds.append(QueryLog.source == source)
    if language:
        conds.append(QueryLog.language == language)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            conds.append(QueryLog.created_at >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            # inclusive end of day
            dt = dt.replace(hour=23, minute=59, second=59)
            conds.append(QueryLog.created_at <= dt)
        except ValueError:
            pass

    where_clause = and_(*conds) if conds else None

    async with async_session_maker() as session:
        count_stmt = select(func.count()).select_from(QueryLog)
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
        total = (await session.execute(count_stmt)).scalar_one()

        rows_stmt = select(QueryLog).order_by(QueryLog.created_at.desc())
        if where_clause is not None:
            rows_stmt = rows_stmt.where(where_clause)
        rows_stmt = rows_stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(rows_stmt)).scalars().all()

        items = [
            {
                "id": str(r.id),
                "question": r.question,
                "answer": r.answer,
                "agent_logs": r.agent_logs,
                "language": r.language,
                "source": r.source,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
            }
            for r in rows
        ]

    pages = (total + page_size - 1) // page_size if total else 1
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
    }
