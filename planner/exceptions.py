class PlannerError(Exception):
    status_code = 500
    code = "planner_error"

    def __init__(self, detail: str, *, code: str | None = None):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code


class InvalidLocationError(PlannerError):
    status_code = 422
    code = "invalid_location"


class RouteNotServiceableError(PlannerError):
    status_code = 422
    code = "route_not_serviceable"


class ProviderUnavailableError(PlannerError):
    status_code = 503
    code = "routing_provider_unavailable"


class ProviderTimeoutError(PlannerError):
    status_code = 504
    code = "routing_provider_timeout"


class StationDataUnavailableError(PlannerError):
    status_code = 503
    code = "station_data_unavailable"
