"""Data models for analysis results."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class FrameworkInfo:
    """Information about detected framework."""

    name: str
    version: Optional[str] = None
    entry_point: Optional[str] = None
    entry_command: Optional[str] = None
    confidence: float = 1.0  # 0.0 to 1.0


@dataclass
class AppSpec:
    """Normalized application specification."""

    app_type: str  # "web", "notebook", "cli", "script"
    listen_port: Optional[int] = None
    is_async: bool = False


@dataclass
class SecretFinding:
    """A detected secret or credential."""

    file: str
    line: int
    type: str  # e.g., "api_key", "password", "token"
    description: str
    value_preview: str  # First/last few chars, redacted middle
    severity: str = "critical"  # critical, high, medium, low


@dataclass
class DependencyInfo:
    """Information about a project dependency."""

    name: str
    version: Optional[str] = None
    pinned: bool = False
    has_known_cves: bool = False
    cve_details: List[str] = field(default_factory=list)
    severity: str = "low"  # critical, high, medium, low


@dataclass
class AIUsageInfo:
    """Information about AI API usage."""

    provider: str  # e.g., "openai", "anthropic", "google"
    sdk: str  # e.g., "openai", "anthropic", "google.generativeai"
    config_method: str  # "hardcoded", "env_var", "secrets_manager", "unknown"
    files: List[str] = field(default_factory=list)
    api_key_pattern: Optional[str] = None


@dataclass
class ExternalServiceInfo:
    """Information about an external service integration."""

    provider: str  # e.g., "Salesforce", "PostgreSQL", "AWS S3"
    category: str  # "crm", "database", "message_queue", "cloud", "office", "http_api"
    sdk: str  # e.g., "simple_salesforce", "psycopg2", "boto3"
    auth_method: str  # "api_key", "oauth", "connection_string", "iam", "unknown"
    domains: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)


@dataclass
class RiskItem:
    """A security or operational risk finding."""

    severity: str  # critical, high, medium, low
    category: str  # e.g., "security", "reliability", "compliance"
    title: str
    description: str
    remediation: str
    files: List[str] = field(default_factory=list)


@dataclass
class AppAnalysis:
    """Complete analysis results for an application."""

    project_path: str
    framework: Optional[FrameworkInfo] = None
    app_spec: Optional[AppSpec] = None
    python_version: Optional[str] = None
    secrets: List[SecretFinding] = field(default_factory=list)
    dependencies: List[DependencyInfo] = field(default_factory=list)
    ai_usage: List[AIUsageInfo] = field(default_factory=list)
    external_services: List[ExternalServiceInfo] = field(default_factory=list)
    risks: List[RiskItem] = field(default_factory=list)

    @property
    def risk_score(self) -> float:
        """Calculate overall risk score (0-100)."""
        score = 0

        # Secrets are critical
        score += len([s for s in self.secrets if s.severity == "critical"]) * 20
        score += len([s for s in self.secrets if s.severity == "high"]) * 10

        # Dependencies with CVEs
        score += len([d for d in self.dependencies if d.has_known_cves and d.severity == "critical"]) * 15
        score += len([d for d in self.dependencies if d.has_known_cves and d.severity == "high"]) * 8

        # Unpinned dependencies
        score += len([d for d in self.dependencies if not d.pinned]) * 2

        # Hardcoded AI keys
        score += len([ai for ai in self.ai_usage if ai.config_method == "hardcoded"]) * 25

        # External services with weak auth
        score += len([es for es in self.external_services if es.auth_method in ("unknown", "connection_string")]) * 5

        # Risk items
        score += len([r for r in self.risks if r.severity == "critical"]) * 15
        score += len([r for r in self.risks if r.severity == "high"]) * 8
        score += len([r for r in self.risks if r.severity == "medium"]) * 3

        return min(score, 100)

    @property
    def risk_level(self) -> str:
        """Get risk level as a string."""
        score = self.risk_score
        if score >= 75:
            return "CRITICAL"
        elif score >= 50:
            return "HIGH"
        elif score >= 25:
            return "MEDIUM"
        else:
            return "LOW"


# --- Profiler models (Phase 3) ---


@dataclass
class ImportRecord:
    """A single import observed at runtime."""

    module_name: str
    source: str  # "stdlib", "third_party", "local"
    file_path: Optional[str] = None
    timestamp: Optional[float] = None


@dataclass
class DependencyProfile:
    """Runtime dependency analysis."""

    declared_deps: List[str] = field(default_factory=list)
    runtime_imports: List[ImportRecord] = field(default_factory=list)
    missing_deps: List[str] = field(default_factory=list)  # imported but not declared
    unused_deps: List[str] = field(default_factory=list)  # declared but not imported


@dataclass
class ResourceMap:
    """Observed runtime resource usage."""

    network_egress: List[Tuple[str, int]] = field(default_factory=list)  # (domain, port)
    filesystem_reads: List[str] = field(default_factory=list)
    filesystem_writes: List[str] = field(default_factory=list)
    env_vars_accessed: List[str] = field(default_factory=list)
    subprocesses: List[str] = field(default_factory=list)


@dataclass
class ProfileResult:
    """Complete profiling results from a runtime session."""

    project_path: str
    dependency_profile: Optional[DependencyProfile] = None
    resource_map: Optional[ResourceMap] = None
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


@dataclass
class HardenContext:
    """Composite of static analysis and optional runtime profiling."""

    analysis: AppAnalysis
    profile: Optional[ProfileResult] = None


# --- Policy models (Phase 4) ---


@dataclass
class FilesystemPolicy:
    """Filesystem access policy."""

    read_only_root: bool = True
    writable_paths: List[str] = field(default_factory=lambda: ["/tmp", "/var/log/app"])
    denied_paths: List[str] = field(default_factory=lambda: [
        "/etc/shadow", "/etc/passwd", "/root", "/proc/kcore",
    ])


@dataclass
class NetworkPolicy:
    """Network egress policy."""

    default_deny: bool = True
    allowed_egress: List[Tuple[str, int]] = field(default_factory=list)  # (domain, port)
    allowed_domains: List[str] = field(default_factory=list)  # wildcard domains


@dataclass
class IdentityPolicy:
    """Identity and access requirements."""

    sso_required: bool = False
    sso_provider: Optional[str] = None  # "okta", "entra", "google"
    oauth_scopes: Dict[str, List[str]] = field(default_factory=dict)  # service -> scopes


@dataclass
class ComputePolicy:
    """Resource and cost limits."""

    cpu_limit: str = "1.0"
    memory_limit: str = "512Mi"
    daily_token_cap: Optional[int] = None
    daily_cost_cap_usd: Optional[float] = 50.0


@dataclass
class SecurityPolicy:
    """Complete security policy for a hardened app."""

    filesystem: FilesystemPolicy = field(default_factory=FilesystemPolicy)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    identity: IdentityPolicy = field(default_factory=IdentityPolicy)
    secrets_required: List[str] = field(default_factory=list)
    compute: ComputePolicy = field(default_factory=ComputePolicy)
