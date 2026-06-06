from .plugin import SourcesPlugin


def setup(app):
    return SourcesPlugin(app)
