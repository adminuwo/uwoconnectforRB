import re

SPECIAL_CHAR_REGEX = re.compile(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?~`]')

def check_password_criteria(password: str) -> dict:
    """
    Checks standard password criteria and returns a dict with individual booleans.
    """
    pwd = str(password or '')
    return {
        'min_length': len(pwd) >= 8,
        'has_upper': bool(re.search(r'[A-Z]', pwd)),
        'has_lower': bool(re.search(r'[a-z]', pwd)),
        'has_number': bool(re.search(r'[0-9]', pwd)),
        'has_special': bool(SPECIAL_CHAR_REGEX.search(pwd)),
    }

def validate_password_strength(password: str) -> tuple[bool, list[str]]:
    """
    Validates password against mandatory platform requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character

    Returns (is_valid, list_of_errors).
    """
    if not password:
        return False, ["Password is required."]

    criteria = check_password_criteria(password)
    errors = []

    if not criteria['min_length']:
        errors.append("Password must be at least 8 characters long.")
    if not criteria['has_upper']:
        errors.append("Password must contain at least one uppercase letter (A-Z).")
    if not criteria['has_lower']:
        errors.append("Password must contain at least one lowercase letter (a-z).")
    if not criteria['has_number']:
        errors.append("Password must contain at least one number (0-9).")
    if not criteria['has_special']:
        errors.append("Password must contain at least one special character (!@#$%^&* etc.).")

    return len(errors) == 0, errors
