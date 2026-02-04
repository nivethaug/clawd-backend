"""
File Utilities module for Clawd Backend.
Handles secure file operations for the code editor.
"""

import os
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

        # Ensure full path starts with base path
        if not str(full).startswith(str(base)):
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
