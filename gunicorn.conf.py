# A SPHEREx FITS download often exceeds gunicorn's 30s default.
# The killed worker makes the proxy answer with an HTML "Internal Server Error".
timeout = 180
graceful_timeout = 30
# One process, two threads: Play and Sum keep at most two FITS open.
worker_class = "gthread"
workers = 1
threads = 2
