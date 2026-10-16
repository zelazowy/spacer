"""Public release version and provenance shared by every entry point.

Bump major for incompatible workflows, minor for changed extraction/rendering
behaviour or features, and patch for fixes that preserve the intended behaviour.
Extraction schema/revision numbers remain separate cache compatibility markers.
"""
from datetime import datetime, timezone

VERSION = '0.9.9'


def created_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def field_description(scene):
    version = scene.get('prepared_with_version', 'unversioned')
    revision = scene.get('iterative_revision')
    return f"v{version}" if version != 'unversioned' else (
        'unversioned' + (f' (iterative revision {revision})' if revision else ''))
