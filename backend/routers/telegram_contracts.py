"""Strict request DTOs for Telegram administration mutations.

They are intentionally independent from router authentication: the router
authenticates first and validates the body second, so malformed unauthenticated
requests never reveal which Telegram-domain operation exists.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class TelegramContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TelegramPreapprovalRequest(TelegramContract):
    telegram_user_id: PositiveInt
    profile_kind: Literal["existing", "new"] = "existing"
    customer_id: PositiveInt | None = None
    email_display: str | None = Field(default=None, min_length=1, max_length=256)
    expected_preapproval_version: NonNegativeInt
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_exact_profile_shape(self) -> "TelegramPreapprovalRequest":
        if self.profile_kind == "existing":
            if self.customer_id is None or self.email_display is not None:
                raise ValueError("existing preapproval requires customer_id only")
        elif self.customer_id is not None or self.email_display is None:
            raise ValueError("new preapproval requires email_display only")
        return self


class ApproveNewRequest(TelegramContract):
    expected_identity_version: PositiveInt
    email_display: str | None = Field(default=None, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ApproveExistingRequest(TelegramContract):
    customer_id: PositiveInt
    expected_identity_version: PositiveInt
    idempotency_key: str = Field(min_length=1, max_length=200)


class IdentityDecisionRequest(TelegramContract):
    expected_identity_version: PositiveInt
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=700)


class UnlinkIdentityRequest(TelegramContract):
    customer_id: PositiveInt
    expected_identity_version: PositiveInt
    idempotency_key: str = Field(min_length=1, max_length=200)


class NodePolicyMutationRequest(TelegramContract):
    provisioning_enabled: bool
    total_bytes: int | str | None = None
    validity_days: int | str | None = None
    client_enabled: bool | str | None = None
    expected_policy_version: NonNegativeInt
    idempotency_key: str = Field(min_length=1, max_length=200)


class TelegramPreapprovalDto(TelegramContract):
    telegram_user_id: int
    profile_kind: Literal["existing", "new"]
    customer_id: int | None
    customer_email: str
    email_source: str | None
    target_node_ids: tuple[int, ...]
    target_snapshot_digest: str | None
    row_version: int
    created_by: str
    created_at: str


class TelegramPreapprovalResponse(TelegramContract):
    preapproval: TelegramPreapprovalDto
    remote_io: Literal["not_started"]


class NodePolicyDto(TelegramContract):
    node_id: int
    provisioning_enabled: bool
    total_bytes: int
    validity_days: int
    client_enabled: bool
    policy_version: int
    updated_by: str


class TelegramFixedProvisioningContract(TelegramContract):
    inbound_id: Literal[1]
    flow: Literal["xtls-rprx-vision"]


class NodePolicyMutationResponse(TelegramContract):
    policy: NodePolicyDto
    fixed_contract: TelegramFixedProvisioningContract


class NodePolicyValidationResponse(TelegramContract):
    eligible: bool
    reason: str | None
    fixed_contract: TelegramFixedProvisioningContract
