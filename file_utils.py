"""
File Utilities module for Clawd Backend.
Handles secure file operations for the code editor.
"""

import os
import re
import base64
from pathlib import Path
from typing import List, Dict, Optional, Any

# Optional: python-magic for better binary detection
try:
    import magic as python_magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False


class FileUtils:
    """Secure file operations for project files."""

    # Binary file extensions that should not be edited
    BINARY_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'svg', 'webp',
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
        'zip', 'tar', 'gz', 'rar', '7z',
        'exe', 'dll', 'so', 'dylib', 'app', 'bin',
        'mp3', 'mp4', 'wav', 'ogg', 'flac', 'avi', 'mov',
        'ttf', 'otf', 'woff', 'woff2', 'eot',
        'psd', 'ai', 'sketch',
        'class', 'jar', 'war',
        'dat', 'sqlite', 'db',
    }

    # Maximum file size to load (10 MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # Maximum size for a single write (2 MB)
    MAX_WRITE_SIZE = 2 * 1024 * 1024

    # Paths that may never be written through file-edit surfaces.
    DENIED_WRITE_PATTERNS = (
        '.env', '.git/', 'id_rsa', 'id_ed25519', '.ssh/',
        '.npmrc', '.pypirc', 'authorized_keys',
    )

    # Content signature pack: (rule name, regex). HIGH-confidence markers.
    CONTENT_SIGNATURES = [
        ('webshell-php', r'eval\s*\(\s*\$_(POST|GET|REQUEST)'),
        ('webshell-php-assert', r'assert\s*\(\s*base64_decode'),
        ('shell-python-reverse', r'socket\.socket\([^)]*\)[\s\S]{0,400}\.connect\([^)]*\)[\s\S]{0,400}/bin/(ba)?sh'),
        ('shell-bash-devtcp', r'/dev/tcp/[0-9]{1,3}\.'),
        ('shell-powershell-enc', r'-EncodedCommand[\s\S]{0,80}Invoke-Expression'),
        ('obfuscated-exec-py', r'(exec|eval|compile)\s*\(\s*base64\.b64decode\s*\('),
        ('obfuscated-exec-js', r'eval\s*\(\s*atob\s*\('),
        ('miner-stratum', r'stratum\+tcp://'),
        ('miner-xmrig', r'xmrig'),
        ('stealer-cookie-exfil', r'document\.cookie[\s\S]{0,200}(fetch|XMLHttpRequest|location\.href)\s*[=(]'),
    ]

    @staticmethod
    def scan_content(relative_path: str, content: str) -> list:
        """Static content signature scan. Returns rule names hit.

        HIGH-confidence markers only — clean files must pass silently.
        """
        findings = []
        lower_name = relative_path.lower()
        for rule, pattern in FileUtils.CONTENT_SIGNATURES:
            try:
                if re.search(pattern, content, re.IGNORECASE):
                    findings.append(rule)
            except re.error:
                continue
        # Long base64 blob heuristic in executable files
        if lower_name.endswith(('.py', '.js', '.ts', '.sh', '.ps1', '.php')):
            for chunk in re.findall(r'[A-Za-z0-9+/=]{2000,}', content):
                findings.append('large-base64-blob')
                break
        return findings

    @staticmethod
    def check_write_allowed(relative_path: str) -> None:
        """Raise ValueError if this relative path is on the denylist."""
        normalized = '/' + relative_path.replace(os.sep, '/').lstrip('/').lower()
        for pat in FileUtils.DENIED_WRITE_PATTERNS:
            marker = pat.rstrip('/') if not pat.endswith('/') else pat.rstrip('/')
            if pat in normalized or f'/{marker}' in normalized:
                raise ValueError(f"Writing to '{pat}' paths is not allowed")

    @staticmethod
    def is_binary_file(filename: str, content: bytes = b'') -> bool:
        """
        Check if file is binary based on extension or content.

        Args:
            filename: File name to check extension
            content: First few bytes of file (optional)

        Returns:
            True if binary, False if text
        """
        # Check extension first
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        if ext in FileUtils.BINARY_EXTENSIONS:
            return True

        # Check content using magic if available
        if content and HAS_MAGIC:
            try:
                mime = python_magic.from_buffer(content[:1024])
                return not mime.startswith('text/') and not mime in ['application/json', 'application/xml']
            except Exception:
                pass

        # Fallback: check for null bytes
        if b'\x00' in content[:1024]:
            return True

        return False

    @staticmethod
    def sanitize_path(base_path: str, relative_path: str) -> str:
        """
        Sanitize path to prevent directory traversal.

        Args:
            base_path: Base directory (should be absolute)
            relative_path: User-provided relative path

        Returns:
            Absolute path within base_path

        Raises:
            ValueError: If path tries to escape base_path
        """
        base = Path(base_path).resolve()
        full = (base / relative_path).resolve()

        # Strict containment: base must be a path-PREFIX component, not a
        # string prefix (otherwise sibling dirs like "<base>-evil" pass).
        if os.path.commonpath([str(base), str(full)]) != str(base):
            raise ValueError(f"Path traversal attempt: {relative_path}")

        return str(full)

    @staticmethod
    def build_file_tree(base_path: str) -> List[Dict[str, Any]]:
        """
        Build file tree structure from directory.

        Args:
            base_path: Absolute path to project directory

        Returns:
            List of file nodes (files and folders)
        """
        base = Path(base_path)

        if not base.exists():
            return []

        nodes = []

        for item in sorted(base.iterdir()):
            # Skip hidden files and directories
            if item.name.startswith('.'):
                continue

            relative_path = item.relative_to(base)

            if item.is_file():
                try:
                    size = item.stat().st_size
                except OSError:
                    size = 0

                nodes.append({
                    'type': 'file',
                    'name': item.name,
                    'path': str(relative_path).replace(os.sep, '/'),
                    'size': size,
                })
            elif item.is_dir():
                children = FileUtils.build_file_tree(str(item))
                if children:  # Only include non-empty directories
                    nodes.append({
                        'type': 'folder',
                        'name': item.name,
                        'path': str(relative_path).replace(os.sep, '/'),
                        'children': children,
                    })

        return nodes

    @staticmethod
    def read_file(base_path: str, file_path: str) -> Dict[str, Any]:
        """
        Read file content safely.

        Args:
            base_path: Base project directory
            file_path: Relative path to file

        Returns:
            Dict with content, is_binary, and size

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is too large
            PermissionError: If cannot read file
        """
        full_path = FileUtils.sanitize_path(base_path, file_path)

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check file size
        size = os.path.getsize(full_path)
        if size > FileUtils.MAX_FILE_SIZE:
            raise ValueError(f"File too large: {size} bytes (max {FileUtils.MAX_FILE_SIZE})")

        # Read file content
        with open(full_path, 'rb') as f:
            content_bytes = f.read()

        # Check if binary
        is_binary = FileUtils.is_binary_file(file_path, content_bytes)

        # Decode content if text
        if is_binary:
            content = ''
        else:
            try:
                content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # If UTF-8 fails, treat as binary
                is_binary = True
                content = ''

        return {
            'content': content,
            'is_binary': is_binary,
            'size': size,
        }

    @staticmethod
    def write_file(base_path: str, file_path: str, content: str) -> Dict[str, Any]:
        """
        Write file content safely.

        Args:
            base_path: Base project directory
            file_path: Relative path to file
            content: File content (text only)

        Returns:
            Dict with success status and file size

        Raises:
            ValueError: If file is binary or path is invalid
            PermissionError: If cannot write file
        """
        full_path = FileUtils.sanitize_path(base_path, file_path)

        # Don't allow writing to binary files
        if FileUtils.is_binary_file(file_path):
            raise ValueError(f"Cannot write to binary file: {file_path}")

        # Denylist: secrets, git metadata, credential stores
        FileUtils.check_write_allowed(file_path)

        # Write size cap
        if len(content) > FileUtils.MAX_WRITE_SIZE:
            raise ValueError(f"Content too large: {len(content)} bytes (max {FileUtils.MAX_WRITE_SIZE})")

        # Content signature scan — HIGH-confidence malware markers block the write
        findings = FileUtils.scan_content(file_path, content)
        if findings:
            raise ValueError(
                f"Blocked by content scan: {', '.join(findings)}. "
                "If you believe this is a false positive, edit the file inside DreamAgent instead.")

        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Write content
        content_bytes = content.encode('utf-8')

        with open(full_path, 'wb') as f:
            f.write(content_bytes)

        size = len(content_bytes)

        return {
            'success': True,
            'size': size,
        }
