"""
backend/komvos/governance/egress.py

Egress control: what stands between a node and the network.

`AccessPolicy.allow_network` / `allowed_domains` existed in the schema long
before anything read them at call time. This module turns them into a gate
that runs BEFORE a request leaves the machine, and records a
GovernanceDecision either way.

Semantics (also documented in this package's README):

- Loopback destinations (127.0.0.1, ::1, localhost) are NOT egress. Traffic to
  them never leaves the machine; local models are governed by
  `allow_local_models`, which is already enforced. A non-loopback Ollama base
  URL (a remote tunnel) IS egress and needs `allow_network`.
- `allow_network=False` denies every non-loopback destination.
- An empty `allowed_domains` on a policy that allows network means "no domain
  restriction", NOT "no domains". The compiler's intersect logic depends on
  this reading (an unrestricted ancestor must not revoke its descendant's
  domains), so enforcement reads it the same way.
- Host matching is not a substring match. A listed entry matches itself and
  any depth of subdomain, compared on dot boundaries: entry "example.com"
  matches "example.com" and "api.example.com" but never "notexample.com".
  Comparison is case-insensitive; ports are not part of the policy.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from komvos.compiler.models import AccessPolicy
from komvos.endpoints.base import AccessDeniedError, ModelEndpoint
from komvos.governance.context import record_decision
from komvos.governance.decisions import DecisionOutcome, GovernanceDomain

#: Host each cloud provider reaches when no custom base_url overrides it.
#: Mirrors the defaults applied inside CloudEndpoint.generate — kept here so
#: the egress decision can name the actual destination. If a provider default
#: changes there, change it here too.
PROVIDER_DEFAULT_HOSTS: dict[str, str] = {
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "google": "generativelanguage.googleapis.com",
    "groq": "api.groq.com",
    "openrouter": "openrouter.ai",
    "zhipu": "open.bigmodel.cn",
    "nvidia": "integrate.api.nvidia.com",
    # OllamaEndpoint's default; overridden by any configured base_url.
    "ollama": "127.0.0.1",
}

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def url_host(url: str) -> str | None:
    """Hostname of a URL string, without port or scheme; None if unparseable."""
    raw = url.strip()
    if "//" not in raw:
        raw = f"//{raw}"
    try:
        return urlsplit(raw).hostname
    except ValueError:
        return None


def endpoint_egress_host(endpoint: ModelEndpoint) -> str | None:
    """
    Best-effort destination host of an endpoint's outbound calls.

    Reads only attributes that already exist on the concrete implementations:
      - CloudEndpoint: `.base_url` override or `.provider` default
      - OllamaEndpoint: `._base_url` (set from resolve_ollama_base, which may
        be a remote tunnel URL)
      - MockEndpoint and anything else with neither attribute: None — nothing
        it does can leave the machine, so egress has no opinion.
    """
    base_url = getattr(endpoint, "base_url", None)
    if isinstance(base_url, str) and base_url:
        host = url_host(base_url)
        if host:
            return host.lower()

    provider = getattr(endpoint, "provider", None)
    if isinstance(provider, str) and provider in PROVIDER_DEFAULT_HOSTS:
        return PROVIDER_DEFAULT_HOSTS[provider]

    ollama_base = getattr(endpoint, "_base_url", None)
    if isinstance(ollama_base, str) and ollama_base:
        host = url_host(ollama_base)
        if host:
            return host.lower()

    return None


def is_loopback(host: str) -> bool:
    """True for hosts whose traffic never leaves the machine."""
    return host.lower() in _LOOPBACK_HOSTS


def host_allowed(host: str, allowed_domains: list[str]) -> bool:
    """
    Dot-boundary host match against the policy's allowed_domains.

    An empty list is unrestricted (see module docstring). Each entry matches
    itself plus any depth of subdomain: "example.com" covers
    "api.example.com" and "api.v2.example.com", never "notexample.com". A
    leading dot on an entry is accepted and ignored. Matching ignores case;
    ports carry no policy meaning and are not part of a host entry.
    """
    normalized = [d.lstrip(".").lower() for d in allowed_domains]
    if not normalized:
        # Empty list = unrestricted, matching intersect()'s reading.
        return True
    host_lower = host.lower()
    return any(host_lower == d or host_lower.endswith(f".{d}") for d in normalized)


async def check_egress(
    *,
    policy: AccessPolicy,
    node_id: str,
    host: str,
    governed_by: tuple[str, ...] = (),
) -> None:
    """
    Gate one non-loopback destination against the node's effective policy.

    Records an ALLOWED decision on pass and a DENIED one before raising
    AccessDeniedError on refusal — the caller raises before any socket work,
    so a denied request never leaves the machine.
    """
    capability = f"egress:{host}"

    if not policy.allow_network:
        await record_decision(
            domain=GovernanceDomain.EGRESS,
            capability=capability,
            outcome=DecisionOutcome.DENIED,
            reason=(
                f"Node '{node_id}' cannot reach '{host}': its effective "
                "policy does not grant allow_network."
            ),
            node_id=node_id,
            effective_policy=policy,
            governed_by=governed_by,
        )
        raise AccessDeniedError(
            node_id=node_id,
            capability=capability,
            detail=(
                f"Node '{node_id}' requires network access to '{host}', "
                "which its access policy does not grant "
                "(allow_network is false). Grant network access on the "
                "governing access node, or point the endpoint at a local "
                "address."
            ),
        )

    if policy.allowed_domains and not host_allowed(host, policy.allowed_domains):
        allowed = ", ".join(policy.allowed_domains)
        await record_decision(
            domain=GovernanceDomain.EGRESS,
            capability=capability,
            outcome=DecisionOutcome.DENIED,
            reason=(
                f"Node '{node_id}' cannot reach '{host}': not in the "
                f"policy's allowed domains [{allowed}]."
            ),
            node_id=node_id,
            effective_policy=policy,
            governed_by=governed_by,
        )
        raise AccessDeniedError(
            node_id=node_id,
            capability=capability,
            detail=(
                f"Node '{node_id}' requires network access to '{host}', "
                f"which is outside its access policy's allowed domains: "
                f"[{allowed}]. Add the domain to 'allowed_domains' on the "
                "governing access node."
            ),
        )

    await record_decision(
        domain=GovernanceDomain.EGRESS,
        capability=capability,
        outcome=DecisionOutcome.ALLOWED,
        reason=(
            f"Node '{node_id}' may reach '{host}': allow_network granted"
            + (
                ""
                if policy.allowed_domains
                else " with no domain restriction"
            )
            + "."
        ),
        node_id=node_id,
        effective_policy=policy,
        governed_by=governed_by,
    )


async def enforce_egress_for_endpoint(
    *,
    endpoint: ModelEndpoint,
    policy: AccessPolicy,
    node_id: str,
    governed_by: tuple[str, ...] = (),
) -> None:
    """
    Full pre-flight for one model call: resolve where the call would land,
    exempt loopback, gate everything else. Called by the model executor
    before generate(), so nothing past this point can send a byte that
    governance did not rule on.
    """
    host = endpoint_egress_host(endpoint)
    if host is None or is_loopback(host):
        return
    await check_egress(
        policy=policy,
        node_id=node_id,
        host=host,
        governed_by=governed_by,
    )
