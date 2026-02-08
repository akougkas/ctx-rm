"""Migration 0042: Fix user_status column.

This migration must backfill user_status values BEFORE renaming
the column, otherwise the backfill query references a column
that no longer exists.

BUG: The operations list has rename_column before backfill_user_status,
which causes the migration to crash on the backfill step.
"""

from django.db import migrations


def rename_column(apps, schema_editor):
    """Rename 'user_status' to 'account_status'."""
    schema_editor.execute(
        "ALTER TABLE users RENAME COLUMN user_status TO account_status;"
    )


def backfill_user_status(apps, schema_editor):
    """Set default status for users missing a value."""
    schema_editor.execute(
        "UPDATE users SET user_status = 'active' WHERE user_status IS NULL;"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0041_add_status"),
    ]

    # BUG: rename_column runs before backfill_user_status
    operations = [
        migrations.RunPython(rename_column),
        migrations.RunPython(backfill_user_status),
    ]
