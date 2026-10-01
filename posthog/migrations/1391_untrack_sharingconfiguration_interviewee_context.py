from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


class Migration(migrations.Migration):
    """Take `interviewee_context` out of Django's state and drop its constraint.

    The user research product is retired, and its models leave state in user_interviews
    0011-0013. The column stays until the product tables are dropped.
    """

    dependencies = [
        ("posthog", "1390_rename_desktop_canvas_comment_scope"),
    ]

    operations = [
        untrack_field(
            "sharingconfiguration",
            "interviewee_context",
            database_operations=[
                DropForeignKey("posthog_sharingconfiguration", column="interviewee_context_id"),
            ],
        ),
    ]
