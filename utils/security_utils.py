import re

def validate_password_strength(password):
    """
    Validates that a password meets the following criteria:
    - At least 8 characters long
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit
    - Contains at least one special character (@$!%*?&)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
        
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
        
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit."
        
    if not re.search(r"[@$!%*?&]", password):
        return False, "Password must contain at least one special character (@$!%*?&)."
        
    return True, "Password is valid."


def validate_nepal_phone_digits(phone_digits):
    """
    Validates Nepal phone digits after +977.
    Rule: exactly 10 digits, and must start with 98 or 97.
    """
    phone_digits = (phone_digits or "").strip()
    if re.fullmatch(r"(98|97)\d{8}", phone_digits):
        return True, phone_digits

    return False, None
