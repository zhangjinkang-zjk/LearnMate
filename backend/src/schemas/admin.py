from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=72, description="新密码，8–72 字节")

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        if len(value.encode("utf-8")) > 72 or not value.strip():
            raise ValueError("密码不能为空且不能超过 72 字节")
        return value


class DeleteUserRequest(BaseModel):
    confirm: bool = Field(description="确认删除，必须为 true")


class ActivityQuery(BaseModel):
    days: Literal[7, 30] = 7
    search: str = Field(default="", max_length=100)
    activity: Literal["all", "active", "inactive"] = "all"
    sort: Literal["study_seconds", "active_days"] = "study_seconds"
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class PushResourceRequest(BaseModel):
    resource_id: int = Field(gt=0)
    user_ids: list[int] = Field(min_length=1, max_length=100)
    message: str = Field(default="", max_length=1000)

    @field_validator("user_ids")
    @classmethod
    def validate_users(cls, value):
        if any(user_id <= 0 for user_id in value):
            raise ValueError("用户标识无效")
        return value


class UpdateResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=2_000_000)


class ReviewResourceRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class UpdateAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    university: str = Field(default="", max_length=100)
    grade: str = Field(default="", max_length=20)
    major: str = Field(default="", max_length=200)
