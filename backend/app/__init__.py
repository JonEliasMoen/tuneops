"""FastAPI application package.

Keep package initialization side-effect free. Deployment runtimes may load
``backend/app/main.py`` directly; importing that module again from here while
it is still initializing creates a circular import.
"""
