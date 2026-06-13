from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    display_name: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    credits_remaining: int
    plan: str
    has_elevenlabs_key: bool = False


class ApiKeysUpdate(BaseModel):
    elevenlabs_api_key: str | None = None
