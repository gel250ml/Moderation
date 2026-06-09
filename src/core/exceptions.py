from fastapi import HTTPException


class ConflictException(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=409,
            detail={"message": message, "code": "CONFLICT"},
        )


class NotFoundException(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=404,
            detail={"message": message, "code": "NOT_FOUND"},
        )


class ValidationException(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=400,
            detail={"message": message, "code": "INVALID_REQUEST"},
        )


class NotOwnerException(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=403,
            detail={"message": message, "code": "NOT_OWNER"},
        )


class ForbiddenException(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=403,
            detail={"message": message, "code": "FORBIDDEN"},
        )