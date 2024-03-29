from itertools import groupby
from operator import itemgetter

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import pgettext_lazy
from django_countries import countries
from django_prices.models import PriceField
from prices import PriceRange

from saleor.account.models import User

ANY_COUNTRY = ''
ANY_COUNTRY_DISPLAY = pgettext_lazy('Country choice', 'Rest of World')
COUNTRY_CODE_CHOICES = [(ANY_COUNTRY, ANY_COUNTRY_DISPLAY)] + list(countries)


class ShippingMethod(models.Model):

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    courier_id = models.TextField(max_length=255, blank=True)

    class Meta:
        permissions = (
            ('view_shipping',
             pgettext_lazy(
                 'Permission description', 'Can view shipping method')),
            ('edit_shipping',
             pgettext_lazy(
                 'Permission description', 'Can edit shipping method')))

    def __str__(self):
        return self.name

    @property
    def countries(self):
        return [str(country) for country in self.price_per_country.all()]

    @property
    def price_range(self):
        prices = [country.price for country in self.price_per_country.all()]
        if prices:
            return PriceRange(min(prices), max(prices))
        return None


class ShippingMethodCountryQueryset(models.QuerySet):

    def unique_for_country_code(self, country_code, shipping_method_country_ids):
        if shipping_method_country_ids:
            return self.filter(id__in=shipping_method_country_ids)

        shipping = self.filter(
            Q(country_code=country_code) |
            Q(country_code=ANY_COUNTRY))
        shipping = shipping.order_by('shipping_method_id')
        shipping = shipping.values_list(
            'shipping_method_id', 'id', 'country_code')
        grouped_shipping = groupby(shipping, itemgetter(0))
        any_country = ANY_COUNTRY

        ids = []

        for dummy_method_id, method_values in grouped_shipping:
            method_values = list(method_values)
            # if there is any country choice and specific one remove
            # any country choice
            if len(method_values) == 2:
                method = [
                    val for val in method_values if val[2] != any_country][0]
            else:
                method = method_values[0]
            ids.append(method[1])
        return self.filter(id__in=ids)


# class Order(models.Model):
#     origin_country = models.CharField(max_length=2, default="SG", choices=COUNTRY_CODE_CHOICES)
#     origin_postal_code = models.CharField(max_length=50)
#     destination_country = models.CharField(max_length=2, default="SG", choices=COUNTRY_CODE_CHOICES)
#     destination_postal_code = models.CharField(max_length=50)
#     items = models.ManyToManyField("product.Product", related_name='orders')


class ShippingMethodCountry(models.Model):
    country_code = models.CharField(
        choices=COUNTRY_CODE_CHOICES, max_length=2, blank=True,
        default=ANY_COUNTRY)
    price = PriceField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12, decimal_places=2)
    shipping_method = models.ForeignKey(
        ShippingMethod, related_name='price_per_country',
        on_delete=models.CASCADE)
    # order = models.ForeignKey(Order, on_delete=models.CASCADE)
    postal_code = models.CharField(max_length=50, blank=True)


    # added
    min_delivery_time = models.IntegerField(null=True, default=2)
    max_delivery_time = models.IntegerField(null=True,default=4 )

    objects = ShippingMethodCountryQueryset.as_manager()

    def __str__(self):
        # https://docs.djangoproject.com/en/dev/ref/models/instances/#django.db.models.Model.get_FOO_display  # noqa
        return '%s %s' % (
            self.shipping_method, self.get_country_code_display())

    def get_total(self):
        return self.price


class Shipment(models.Model):

    easyship_shipment_id = models.CharField(max_length=255)
    platform_order_number = models.CharField(max_length=255)
    min_delivery_time = models.IntegerField()
    max_delivery_time = models.IntegerField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shipments', null=True, blank=True)

