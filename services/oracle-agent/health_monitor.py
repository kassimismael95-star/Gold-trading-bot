
"""Host health checks that feed capacity reporting without exposing secrets."""

import logging
import shutil

from resource_monitor import ResourceMonitor

log = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(self, resource_monitor=None):
        self.resources = resource_monitor or ResourceMonitor()

    def check(self):
        metrics = self.resources.sample()

        disk_free = metrics.get(
            "disk_free_bytes",
            shutil.disk_usage("/").free,
        )

        memory_percent = metrics.get("memory_percent", 0)
        cpu_percent = metrics.get("cpu_percent", 0)

        if disk_free < 2 * 1024**3:
            log.warning("Low free disk space on execution host")

        if memory_percent > 90:
            log.warning("High memory pressure on execution host")

        if cpu_percent > 95:
            log.warning("High CPU usage on execution host")

        return metrics
