# Generated for Apollo enrichment fields on Contact model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='contact',
            name='job_title',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='contact',
            name='company_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='contact',
            name='company_website',
            field=models.URLField(blank=True, default='', max_length=2000),
        ),
        migrations.AddField(
            model_name='contact',
            name='linkedin_url',
            field=models.URLField(blank=True, default='', max_length=2000),
        ),
        migrations.AddField(
            model_name='contact',
            name='company_linkedin_url',
            field=models.URLField(blank=True, default='', max_length=2000),
        ),
        migrations.AddField(
            model_name='contact',
            name='company_industry',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='contact',
            name='company_employee_count',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='contact',
            name='career_history',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='contact',
            name='apollo_person_id',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='contact',
            name='email_status',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
    ]
