from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.entities import TraceRow


class TraceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, turn_id: str, payload: dict) -> None:
        self.db.add(TraceRow(turn_id=turn_id, payload_json=json.dumps(payload, ensure_ascii=False)))
        self.db.commit()
