"""Configuration loader.

Loads application configuration for the current environment.

BUG: Hardcodes production values instead of reading from the
ENV environment variable. The test harness sets ENV=staging,
so this code must use os.getenv('ENV') to detect the environment.
"""


# BUG: Hardcoded to production instead of reading from os.getenv('ENV')
ENVIRONMENT = "production"


def load_config() -> dict:
    """Load configuration for the current environment.

    BUG: Always returns production config because ENVIRONMENT
    is hardcoded. Should use os.getenv('ENV') to determine
    the active environment.
    """
    if ENVIRONMENT == "production":
        return {
            "db_host": "prod-db.internal",
            "db_port": 5432,
            "debug": False,
            "log_level": "WARNING",
        }
    elif ENVIRONMENT == "staging":
        return {
            "db_host": "staging-db.internal",
            "db_port": 5432,
            "debug": True,
            "log_level": "DEBUG",
        }
    else:
        return {
            "db_host": "localhost",
            "db_port": 5432,
            "debug": True,
            "log_level": "DEBUG",
        }


def get_db_url() -> str:
    """Build a database connection URL from config."""
    cfg = load_config()
    return f"postgresql://{cfg['db_host']}:{cfg['db_port']}/app"
