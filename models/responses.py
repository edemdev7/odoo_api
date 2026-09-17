from pydantic import BaseModel
from typing import Optional, Any

class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    message: str = ""
    count: Optional[int] = None
