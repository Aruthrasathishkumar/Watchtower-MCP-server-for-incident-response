"""Kubernetes event collector for WatchTower.

Maintains a watch stream against the Kubernetes events API and writes
each event as a WatchTower event row. Handles reconnects automatically.

Usage::

    python -m collectors.k8s.collector                   # watch forever
    python -m collectors.k8s.collector --namespace boutique
    python -m collectors.k8s.collector --once            # bulk-load current events and exit

The --once mode is useful for populating the event store with events
that already exist. Without it the collector only captures events that
happen while the collector is running.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

# Allow running as a module from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException
from watchtower.config import Config, configure_logging, load_config
from watchtower.db import connection

from collectors.github.writer import write_events  # Reuses the same writer!

from .mapper import k8s_event_to_row


log = logging.getLogger("collector.k8s")

_shutdown_requested = False


def _install_signal_handlers() -> None:
    """Clean shutdown on Ctrl+C."""
    def handler(signum, frame):
        global _shutdown_requested
        log.info("Shutdown requested (signal %s). Finishing current iteration...", signum)
        _shutdown_requested = True
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _load_kube_config() -> None:
    """Try in-cluster config first, then local kubeconfig."""
    try:
        config.load_incluster_config()
        log.info("Using in-cluster Kubernetes config")
    except config.ConfigException:
        config.load_kube_config()
        log.info("Using local kubeconfig")


def load_existing_events(cfg: Config, namespace: str | None) -> int:
    """One-shot load of current K8s events into the event store."""
    _load_kube_config()
    v1 = client.CoreV1Api()

    if namespace:
        result = v1.list_namespaced_event(namespace)
    else:
        result = v1.list_event_for_all_namespaces()

    rows = [k8s_event_to_row(ev) for ev in result.items]
    if not rows:
        log.info("No existing events found%s",
                 f" in namespace {namespace}" if namespace else "")
        return 0

    with connection(cfg) as conn:
        inserted = write_events(conn, rows)

    log.info("Bulk load: %d events seen, %d new inserted", len(rows), inserted)
    return inserted


def watch_events(cfg: Config, namespace: str | None) -> None:
    """Stream K8s events into the event store.

    Handles disconnects by reconnecting with a short backoff. This is how
    production K8s clients stay connected indefinitely.
    """
    _load_kube_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()

    resource_version: str | None = None
    backoff = 1  # seconds; resets to 1 on successful connect

    log.info("Watching K8s events%s", f" in namespace '{namespace}'" if namespace else " across all namespaces")

    while not _shutdown_requested:
        try:
            kwargs: dict[str, Any] = {"timeout_seconds": 300}
            if resource_version:
                kwargs["resource_version"] = resource_version

            stream_fn = (
                v1.list_namespaced_event if namespace else v1.list_event_for_all_namespaces
            )
            args: list[Any] = [namespace] if namespace else []

            with connection(cfg) as conn:
                for event in w.stream(stream_fn, *args, **kwargs):
                    if _shutdown_requested:
                        break

                    k8s_event = event["object"]
                    # Save resource_version so reconnects resume from here
                    resource_version = k8s_event.metadata.resource_version

                    try:
                        row = k8s_event_to_row(k8s_event)
                        inserted = write_events(conn, [row])
                        if inserted:
                            log.info(
                                "  [%s] %s: %s",
                                row["severity"],
                                row["service"],
                                row["title"],
                            )
                    except Exception as exc:
                        log.warning("Failed to process event: %s", exc)

            backoff = 1  # clean disconnect, reset backoff

        except ApiException as exc:
            if exc.status == 410:
                # 410 Gone = our resource_version is too old, start fresh
                log.info("Resource version expired, restarting from latest")
                resource_version = None
                continue
            log.warning("K8s API error: %s (retrying in %ds)", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

        except Exception as exc:
            log.exception("Watch stream died: %s (retrying in %ds)", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    log.info("Watch loop exited cleanly.")


def main() -> int:
    parser = argparse.ArgumentParser(description="WatchTower Kubernetes collector")
    parser.add_argument("--namespace", default="boutique",
                        help="Namespace to watch (default: boutique). Use '' for all namespaces.")
    parser.add_argument("--once", action="store_true",
                        help="Bulk-load existing events once and exit (no watch).")
    args = parser.parse_args()

    cfg = load_config()
    configure_logging(cfg.log_level)
    _install_signal_handlers()

    namespace = args.namespace or None

    if args.once:
        load_existing_events(cfg, namespace)
    else:
        watch_events(cfg, namespace)

    return 0


if __name__ == "__main__":
    sys.exit(main())