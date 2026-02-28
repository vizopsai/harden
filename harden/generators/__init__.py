"""OSS generators (Dockerfile + SBOM + docker-compose + egress proxy)."""

from .dockerfile import generate_dockerfile, generate_dockerignore
from .sbom import generate_sbom, generate_spdx_sbom
from .compose import generate_compose
from .egress_proxy import generate_squid_config, collect_egress_domains

__all__ = [
    "generate_dockerfile",
    "generate_dockerignore",
    "generate_sbom",
    "generate_spdx_sbom",
    "generate_compose",
    "generate_squid_config",
    "collect_egress_domains",
]
