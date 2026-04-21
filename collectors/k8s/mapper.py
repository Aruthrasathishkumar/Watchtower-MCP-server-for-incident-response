"""Map Kubernetes events to WatchTower event rows.

Kept separate from the watch/streaming logic so it's easy to unit-test.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# A pod name like "frontend-849f6b48f8-8llnh" has the deployment name
# ("frontend") followed by a replicaset hash and a pod ID. Strip them to
# recover the deployment name. Works for most K8s naming conventions.
_POD_SUFFIX_RE = re.compile(r"-[a-z0-9]{5,10}(-[a-z0-9]{5})?$")


def _extract_service(obj_kind: str, obj_name: str) -> str:
    """Extract the logical service name from a K8s object name."""
    if not obj_name:
        return "(unknown)"
    # For Pods and ReplicaSets, strip the random suffix.
    if obj_kind in {"Pod", "ReplicaSet"}:
        return _POD_SUFFIX_RE.sub("", obj_name)
    # For Deployments, Services, ConfigMaps etc, the name IS the service.
    return obj_name


def k8s_event_to_row(event: Any) -> dict[str, Any]:
    """Convert a kubernetes.client.V1Event into a WatchTower event dict.

    ``event`` is a V1Event object from the kubernetes client library.
    """
    # K8s events prefer event_time, but older clusters only populate
    # last_timestamp or first_timestamp. Fall back through them.
    timestamp = (
        event.event_time
        or event.last_timestamp
        or event.first_timestamp
        or datetime.now(timezone.utc)
    )
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    obj = event.involved_object
    obj_kind = obj.kind or "Unknown"
    obj_name = obj.name or "(unnamed)"
    service = _extract_service(obj_kind, obj_name)

    severity = "warning" if (event.type or "").lower() == "warning" else "info"

    # Short, human-readable title
    title = f"{event.reason or 'Event'}: {obj_kind}/{obj_name}"[:500]

    return {
        "timestamp": timestamp,
        "event_type": "k8s_event",
        "severity": severity,
        "service": service,
        "actor": event.reporting_component or (event.source.component if event.source else None),
        "source_system": "kubernetes",
        "source_id": event.metadata.uid,
        "title": title,
        "payload": {
            "reason": event.reason,
            "message": event.message,
            "k8s_type": event.type,
            "involved_object": {
                "kind": obj_kind,
                "name": obj_name,
                "namespace": obj.namespace,
                "uid": obj.uid,
            },
            "count": event.count,
            "first_seen": event.first_timestamp.isoformat() if event.first_timestamp else None,
            "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None,
            "reporting_component": event.reporting_component,
            "reporting_instance": event.reporting_instance,
        },
    }