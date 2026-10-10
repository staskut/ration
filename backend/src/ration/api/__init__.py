"""HTTP and WebSocket surface.

This layer handles transport: routing, serialisation, authentication and
authorisation. It contains no arithmetic — totals, validation and shopping lists
all come from `ration.domain`, which has no idea HTTP exists.
"""
