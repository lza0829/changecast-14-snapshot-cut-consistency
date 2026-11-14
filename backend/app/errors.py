class ConflictError(Exception):
    """A stream already has an operation in flight, or a binding conflicts
    with the current committed watermark. Mapped to HTTP 409."""

    pass
