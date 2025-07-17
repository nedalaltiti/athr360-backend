"""
Utility for getting bot name with app instance suffix.
"""

from athr360.config.app_config import get_current_app_config

def get_bot_name() -> str:
    """
    Get bot name with app instance suffix.
    
    Returns:
        Bot name like "athar360-jo" or "athar360-us"
    """
    try:
        app_config = get_current_app_config()
        return f"athar360-{app_config.instance_id}"
    except Exception:
        # Fallback to default if app config not available
        return "athar360"
        
def get_bot_display_name() -> str:
    """
    Get bot display name for UI.
    
    Returns:
        Display name like "ATHAR360 Compliance PDPL (Jo)" or "ATHAR360 Compliance PDPL (US)"
    """
    try:
        app_config = get_current_app_config()
        return f"ATHAR360 Compliance PDPL ({app_config.name})"
    except Exception:
        return "ATHAR360 Compliance PDPL" 