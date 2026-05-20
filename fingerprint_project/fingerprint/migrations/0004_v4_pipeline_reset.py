"""
Migration 0004: v4 pipeline reset
──────────────────────────────────
- Adds fingerprint_image_size field to Student model
- Clears all stale enrolled fingerprint data (enrolled under old 512x512 pipeline)

Re-enrollment is required for all students after this migration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fingerprint', '0003_initial_full'),
    ]

    operations = [
        # Add the new image-size tracking field
        migrations.AddField(
            model_name='student',
            name='fingerprint_image_size',
            field=models.CharField(
                blank=True,
                default='',
                help_text="Stored as 'WxH', e.g. '400x500'. Used to reshape fingerprint_image bytes.",
                max_length=20,
            ),
        ),

        # Make fingerprint_template and fingerprint_hash nullable/blank
        # so students without enrolled fingerprints are valid
        migrations.AlterField(
            model_name='student',
            name='fingerprint_template',
            field=models.BinaryField(default=b''),
        ),
        migrations.AlterField(
            model_name='student',
            name='fingerprint_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),

        # Clear all stale fingerprint data enrolled under the old pipeline
        # (512x512 images are incompatible with the new 400x500 v4 pipeline)
        migrations.RunSQL(
            sql="""
                UPDATE students
                SET fingerprint_image      = NULL,
                    fingerprint_template   = '',
                    fingerprint_hash       = '',
                    fingerprint_image_size = ''
                WHERE fingerprint_image IS NOT NULL
                   OR fingerprint_template != ''
                   OR fingerprint_hash     != '';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
