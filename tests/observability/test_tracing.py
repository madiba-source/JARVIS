from app.observability.config import ObservabilityConfig
from app.observability.tracing import LocalTracer


def test_nested_and_sibling_span_context_is_restored() -> None:
    tracer = LocalTracer(ObservabilityConfig(max_trace_count=2, max_spans_per_trace=5))
    with tracer.start_span("request") as request:
        trace_id = request.trace_id
        with tracer.start_span("model") as model:
            assert model.parent_span_id == request.span_id
        with tracer.start_span("tool") as tool:
            assert tool.parent_span_id == request.span_id
    spans = tracer.completed_trace(trace_id)
    assert [span.name for span in spans] == ["model", "tool", "request"]


def test_span_attributes_events_and_traces_are_bounded() -> None:
    tracer = LocalTracer(ObservabilityConfig(max_trace_count=1, max_spans_per_trace=1, max_span_attributes=1, max_span_events=1))
    with tracer.start_span("one") as span:
        span.set_attribute("a", "1")
        span.set_attribute("b", "2")
        span.add_event("first")
        span.add_event("second")
    assert len(span.attributes) == 1
    assert len(span.events) == 1
    assert tracer.trace_count == 1
