# A SPHEREx FITS download often exceeds gunicorn's 30s default.
# The killed worker makes the proxy answer with an HTML "Internal Server Error".
timeout = 180
graceful_timeout = 30
