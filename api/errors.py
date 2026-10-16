"""One error shape for every failure: {"error": "<code>", "message": "..."}."""


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
