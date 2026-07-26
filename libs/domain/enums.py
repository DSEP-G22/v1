"""Domain enums shared by contracts, policy, and state machine. No I/O."""

from __future__ import annotations

from enum import Enum


class Modality(str, Enum):
    text = "text"
    audio = "audio"
    image = "image"


class Channel(str, Enum):
    web_portal = "web_portal"
    email = "email"
    phone = "phone"
    chat = "chat"


class TicketState(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    AGGREGATED = "AGGREGATED"
    TRIAGED = "TRIAGED"
    DIAGNOSED = "DIAGNOSED"
    READY_FOR_AGENT = "READY_FOR_AGENT"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class AttachmentStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class Department(str, Enum):
    technical_support = "technical_support"
    billing = "billing"
    network_operations = "network_operations"
    field_service = "field_service"
    sales = "sales"
    retention = "retention"
    general = "general"


class PriorityBand(str, Enum):
    critical = "critical"
    high = "high"
    normal = "normal"
    low = "low"


class Sentiment(str, Enum):
    angry = "angry"
    frustrated = "frustrated"
    neutral = "neutral"
    satisfied = "satisfied"


class DecisionType(str, Enum):
    APPROVE_SEND = "APPROVE_SEND"
    EDIT = "EDIT"
    REJECT = "REJECT"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"
    EXECUTE_ACTION = "EXECUTE_ACTION"


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class FlagCode(str, Enum):
    PARTIAL_PAYLOAD = "PARTIAL_PAYLOAD"
    LOW_ASR_CONFIDENCE = "LOW_ASR_CONFIDENCE"
    LOW_VLM_CONFIDENCE = "LOW_VLM_CONFIDENCE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    RETRIEVAL_EMPTY = "RETRIEVAL_EMPTY"
    UNVERIFIED_CITATION = "UNVERIFIED_CITATION"
    PII_DETECTED = "PII_DETECTED"
    NO_DRAFT = "NO_DRAFT"
