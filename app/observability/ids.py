import uuid


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def generate_session_id() -> str:
    return f"ses_{uuid.uuid4().hex}"


def generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def generate_span_id() -> str:
    return uuid.uuid4().hex[:16]
