# Check length - allow empty/None
    if domain is None or domain.strip() == '':
        return True

    if len(domain) < 3 or len(domain) > 50:
        return False

    # Check if lowercase
    if domain and domain != domain.lower():
        return False

    # Check format: lowercase letters, numbers, hyphens only, must start with letter
    pattern = r'^[a-z0-9-]*$'
    return bool(re.match(pattern, domain))

(domain: str) -> bool:
    """
    Validate subdomain format.

    Rules:
    - Lowercase only
    - Only a-z, 0-9, hyphens
    - No dots, underscores, spaces, or special characters
    - Must start with a letter
    - Length: 3-50 characters

    Args:
        domain: Subdomain string to validate

    Returns:
        True if valid, False otherwise
    """