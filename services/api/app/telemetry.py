from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_telemetry(app: FastAPI) -> bool:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") and not os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    ):
        return False
    provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "elexion-api"),
                SERVICE_VERSION: app.version,
                "deployment.environment.name": os.getenv(
                    "OTEL_DEPLOYMENT_ENVIRONMENT", "development"
                ),
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    return True
