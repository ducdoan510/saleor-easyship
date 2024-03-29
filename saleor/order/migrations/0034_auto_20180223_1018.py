# Generated by Django 2.0.2 on 2018-02-23 16:18

from django.db import migrations
import django_prices.models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0033_auto_20180123_0832'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='discount_amount',
            field=django_prices.models.PriceField(blank=True, currency='SGD', decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='shipping_price',
            field=django_prices.models.PriceField(currency='SGD', decimal_places=4, default=0, editable=False, max_digits=12),
        ),
        migrations.AlterField(
            model_name='order',
            name='total_net',
            field=django_prices.models.PriceField(blank=True, currency='SGD', decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='total_tax',
            field=django_prices.models.PriceField(blank=True, currency='SGD', decimal_places=2, max_digits=12, null=True),
        ),
    ]
