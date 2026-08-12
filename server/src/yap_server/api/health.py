from yap_server.schemas import HealthView, ServerCapabilities


_HEALTH_VIEW = HealthView(
    service="yap-server",
    status="ok",
    api_version="1",
    auth="not_configured",
    capabilities=ServerCapabilities(
        batch_jobs=False,
        live_streaming=False,
        job_status=False,
        transcript_correction=False,
    ),
)


def health(
    *,
    batch_jobs: bool = False,
    authentication_required: bool = False,
    transcript_correction: bool = False,
) -> dict[str, object]:
    if not batch_jobs and not authentication_required and not transcript_correction:
        return _HEALTH_VIEW.to_wire()
    return HealthView(
        service="yap-server",
        status="ok",
        api_version="1",
        auth="required" if authentication_required else "not_configured",
        capabilities=ServerCapabilities(
            batch_jobs=batch_jobs,
            live_streaming=False,
            job_status=batch_jobs,
            transcript_correction=transcript_correction,
        ),
    ).to_wire()
