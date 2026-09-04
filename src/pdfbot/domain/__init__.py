"""Pure domain layer.

Nothing here imports aiogram or celery. Everything takes plain paths, enums and dataclasses, so it
runs identically inside a Celery worker, a unit test, or a REPL.
"""
