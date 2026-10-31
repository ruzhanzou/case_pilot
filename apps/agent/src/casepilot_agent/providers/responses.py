"""Responses transport contract shared by API stages and worker generation."""
from urllib.parse import urlsplit, urlunsplit


def responses_base_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if (parts.scheme not in {"http", "https"} or not parts.netloc or parts.username
            or parts.password or parts.query or parts.fragment):
        raise ValueError("agent_endpoint_invalid")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        raise ValueError("agent_api_type_mismatch")
    if path.endswith("/responses"):
        path = path[:-len("/responses")]
    return urlunsplit((parts.scheme, parts.netloc, path + "/", "", ""))


def responses_model(*, model, openai_client):
    from agents import OpenAIResponsesModel

    class CompletedResponsesModel(OpenAIResponsesModel):
        async def _fetch_response(self, *args, **kwargs):
            response = await super()._fetch_response(*args, **kwargs)
            # These domain stages are non-streaming. A valid-looking partial
            # JSON document is still not a completed model result.
            status = getattr(response, "status", None)
            if status is not None and status != "completed":
                raise ValueError("provider_incomplete_response")
            return response

    return CompletedResponsesModel(model=model, openai_client=openai_client)
