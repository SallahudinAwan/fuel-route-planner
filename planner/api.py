from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and response.status_code == 400:
        fields = response.data
        response.data = {
            "error": {
                "code": "invalid_request",
                "detail": "Request validation failed.",
                "fields": fields,
            }
        }
    return response
