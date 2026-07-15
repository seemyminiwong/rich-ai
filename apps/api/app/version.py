"""Single source of truth for the application version.

The backend, health endpoint and Docker image tags all derive from here.
Keep apps/web/index.html (the ?v= cache-busting query) in sync on release.
"""

__version__ = "12.0"
