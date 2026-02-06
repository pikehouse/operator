"""Cloud subject implementations for distributed eval execution.

Cloud subjects run infrastructure on cloud VMs instead of local Docker,
enabling dangerous chaos types (disk_pressure, memory_exhaustion) that
are unsafe on laptops.
"""

from eval.subjects.cloud.base import CloudVM, CloudSubjectBase

__all__ = ["CloudVM", "CloudSubjectBase"]
