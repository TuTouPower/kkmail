"""HTTP layer (FastAPI).

The ASGI application is ``mail_core.api.app:app``. Routers: ``auth_routes``, ``accounts``,
``mail``, ``sse``. Routes call ``mail_core.mail.application`` / ``mail_core.accounts`` only.
"""
