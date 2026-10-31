from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VehicleOperationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    rfid_uid: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    source: Literal["api", "controller", "simulation"] = Field(default="api", exclude=True)

    @field_validator("rfid_uid", "idempotency_key", mode="before")
    @classmethod
    def strip_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("rfid_uid")
    @classmethod
    def normalize_rfid_uid(cls, value: str) -> str:
        return value.upper()


class HardwareEventRequest(BaseModel):
    event_type: Literal["rfid_read", "gate_opened", "gate_closed"]
    operation: Literal["entry", "exit"]
    operation_key: str = Field(min_length=1, max_length=128)
    rfid_uid: str = Field(min_length=1, max_length=128)

    @field_validator("rfid_uid", "operation_key", mode="before")
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
    slot_id: int = Field(ge=1)
    slot_name: str
    optimizer: str
    allocation_cost: float = Field(ge=0, le=1)
    entered_at: str
    first_hour_rate_paise: int = 5000
    additional_hour_rate_paise: int = 4000
    grace_minutes: int = 10
    daily_cap_paise: int = 40000
    amount_due_paise: int = 0
    receipt_url: str = ""
    gate_action: Literal["open"] = "open"


class ExitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: int
    rfid_uid: str
    slot_id: int = Field(ge=1)
    slot_name: str
    exited_at: str
    entered_at: str = ""
    duration_seconds: int = 0
    amount_paid_paise: int = 0
    first_hour_rate_paise: int = 5000
    additional_hour_rate_paise: int = 4000
    grace_minutes: int = 10
    daily_cap_paise: int = 40000
    receipt_url: str = ""
    gate_action: Literal["open"] = "open"


class ParkingSlotStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int = Field(ge=1)
    name: str
    walking_distance: float = Field(ge=0, le=1)
    zone: str
    occupied: bool
    updated_at: str
    active_session_id: int | None = None
    rfid_uid: str | None = None
    entered_at: str | None = None
    amount_due_paise: int | None = None


class ParkingStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    slots: tuple[ParkingSlotStatus, ...]
    event_cursor: int = 0

    @model_validator(mode="after")
    def non_empty_unique_slots(self) -> ParkingStatusResponse:
        if not self.slots:
            raise ValueError("parking status requires at least one slot")
        if len({slot.id for slot in self.slots}) != len(self.slots):
            raise ValueError("parking status slot ids must be unique")
        return self


class ParkingSlotRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int = Field(ge=1)
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
