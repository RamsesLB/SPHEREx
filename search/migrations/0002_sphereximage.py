from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('search', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SpherexImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('obs_id', models.CharField(max_length=255)),
                ('access_url', models.URLField(max_length=1000, unique=True)),
                ('ra_center', models.FloatField()),
                ('dec_center', models.FloatField()),
                ('ra_min', models.FloatField(blank=True, null=True)),
                ('ra_max', models.FloatField(blank=True, null=True)),
                ('dec_min', models.FloatField(blank=True, null=True)),
                ('dec_max', models.FloatField(blank=True, null=True)),
                ('observation_date', models.DateTimeField()),
                ('band', models.CharField(blank=True, default='', max_length=80)),
                ('detector', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('em_min', models.FloatField(blank=True, null=True)),
                ('em_max', models.FloatField(blank=True, null=True)),
                ('collection', models.CharField(blank=True, default='', max_length=64)),
            ],
            options={
                'ordering': ['observation_date', 'obs_id'],
            },
        ),
    ]
