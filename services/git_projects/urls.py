"""Git URL validation — HTTPS-only, SSRF-safe, redirect-blocked.

v1 restricts to validated public HTTPS Git URLs. Blocks:
- file://, git://, ssh://, ext::, http:// (non-TLS)
- Private IPs (RFC1918, link-local, loopback, ULA, multicast)
- Cloud metadata endpoints (169.254.169.254, metadata.google.internal)
- Userinfo in URL (https://token@host/)
- Redirects (enforced at clone time via http.followRedirects=false)
"""
import ipaddress
import logging
import socket
import urllib.parse

logger = logging.getLogger(__name__)

# Schemes that are allowed
ALLOWED_SCHEMES = {"https"}

# Hosts that are always blocked (cloud metadata, internal services)
BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
    "instance-data",
}

# Ports that are allowed (443 = default HTTPS)
ALLOWED_PORTS = {443, None}


class GitUrlValidator:
    """Validates Git repository URLs for safe cloning."""

    @staticmethod
    def validate(url: str) -> tuple[bool, str]:
        """Validate a Git URL. Returns (is_valid, error_message).
        
        Rules:
        1. Must be HTTPS
        2. Host must be a public DNS name (or known Git provider)
        3. No userinfo in URL
        4. No private/loopback/link-local IPs
        5. Port must be 443 or omitted
        """
        if not url or not isinstance(url, str):
            return False, "URL is required"

        url = url.strip()
        if len(url) > 2048:
            return False, "URL too long (max 2048 chars)"

        # Parse
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return False, "Invalid URL format"

        # Scheme check
        if parsed.scheme not in ALLOWED_SCHEMES:
            return False, f"Only HTTPS URLs are allowed (got: {parsed.scheme or 'none'})"

        # Host check
        host = parsed.hostname
        if not host:
            return False, "URL must have a hostname"

        if host.lower() in BLOCKED_HOSTS:
            return False, "Blocked host (cloud metadata or internal service)"

        # Userinfo check (https://token@host/ — credentials in URL)
        if parsed.username or parsed.password:
            return False, "Credentials in URL are not allowed"

        # Port check (parsed.port raises ValueError for malformed ports like :abc)
        try:
            port = parsed.port
        except ValueError:
            return False, "Invalid port number"
        if port and port not in ALLOWED_PORTS:
            return False, f"Port {port} not allowed (HTTPS only)"

        # Path check (must look like a git repo path)
        path = parsed.path or ""
        if not path or path == "/":
            return False, "URL must include a repository path (e.g., /user/repo.git)"

        # Private IP check — resolve DNS and verify all IPs are public
        try:
            addr_infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for ai in addr_infos:
                ip = ipaddress.ip_address(ai[4][0])
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_unspecified
                    or ip.is_reserved
                ):
                    return False, f"Private or reserved IP address: {ip}"
        except socket.gaierror:
            return False, f"Cannot resolve hostname: {host}"
        except Exception as exc:
            return False, f"DNS resolution error: {exc}"

        return True, ""

    @staticmethod
    def normalize(url: str) -> str:
        """Normalize a Git URL (strip trailing .git, remove fragments)."""
        url = url.strip().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        return url

    @staticmethod
    def extract_info(url: str) -> dict:
        """Extract provider, owner, repo from a Git URL."""
        url = GitUrlValidator.normalize(url)
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        path_parts = [p for p in (parsed.path or "").split("/") if p]

        info = {"provider": "generic", "host": host, "owner": "", "repo": ""}

        if host == "github.com" or host.endswith(".github.com"):
            info["provider"] = "github"
            if len(path_parts) >= 2:
                info["owner"] = path_parts[0]
                info["repo"] = path_parts[1]
        elif host == "gitlab.com" or host.endswith(".gitlab.com"):
            info["provider"] = "gitlab"
            if len(path_parts) >= 2:
                info["owner"] = path_parts[0]
                info["repo"] = path_parts[-1]
        elif host == "bitbucket.org":
            info["provider"] = "bitbucket"
            if len(path_parts) >= 2:
                info["owner"] = path_parts[0]
                info["repo"] = path_parts[1]
        elif len(path_parts) >= 2:
            info["owner"] = path_parts[0]
            info["repo"] = path_parts[-1]

        return info
