from .plugin import WebPlugin


def setup(app):
    return WebPlugin(app)
