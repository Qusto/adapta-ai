"""One-off: clear chat/ticket history for the demo company.

Deletes ai_messages rows for all users of the demo company (default
11111111-1111-1111-1111-111111111111). HR inbox tickets are derived from
ai_messages, so this clears both the migrant chat history AND the HR inbox.
Users, company, documents and ChromaDB vectors are left intact.

    docker exec infra-api-1 python -m scripts.clear_chat_history
    # or a different company:
    ADAPTA_DEMO_COMPANY_ID=<uuid> docker exec ... python -m scripts.clear_chat_history
"""

from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import delete, func, select

from app.database import async_session_factory
from app.db.models import AiMessage, User

_DEMO_COMPANY_ID = uuid.UUID(
    os.environ.get("ADAPTA_DEMO_COMPANY_ID", "11111111-1111-1111-1111-111111111111")
)


async def main() -> None:
    async with async_session_factory() as session:
        user_ids_subq = select(User.id).where(User.company_id == _DEMO_COMPANY_ID)
        before = await session.scalar(
            select(func.count())
            .select_from(AiMessage)
            .where(AiMessage.user_id.in_(user_ids_subq))
        )
        print(f"clear_chat_history: {before} ai_messages for company {_DEMO_COMPANY_ID}")
        await session.execute(
            delete(AiMessage).where(AiMessage.user_id.in_(user_ids_subq))
        )
        await session.commit()
        print("clear_chat_history: done — chat history + HR inbox cleared")


if __name__ == "__main__":
    asyncio.run(main())
