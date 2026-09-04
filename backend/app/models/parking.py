from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VehicleOperationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    rfid_uid: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("rfid_uid", "idempotency_key", mode="before")
    @classmethod
    def strip_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("rfid_uid")
    @classmethod
    def normalize_rfid_uid(cls, value: str) -> str:
        return value.upper()


class EntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: int
    rfid_uid: str
    slot_id: int = Field(ge=1, le=5)
    slot_name: str
    optimizer: Literal["ga", "pso", "aco"]
    allocation_cost: float = Field(ge=0, le=1)
    entered_at: str
    gate_action: Literal["open"] = "open"


class ExitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: int
    rfid_uid: str
    slot_id: int = Field(ge=1, le=5)
    slot_name: str
    exited_at: str
    gate_action: Literal["open"] = "open"


class ParkingSlotStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int = Field(ge=1, le=5)
    name: str
    walking_distance: float = Field(ge=0, le=1)
    zone: str
    occupied: bool
    updated_at: str
    active_session_id: int | None
    rfid_uid: str | None


class ParkingStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    slots: tuple[ParkingSlotStatus, ...] = Field(min_length=5, max_length=5)


class ParkingSlotRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int = Field(ge=1, le=5)
    name: str
    walking_distance: float = Field(ge=0, le=1)
    zone: str
    occupied: bool
    updated_at: str


class ParkingConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
