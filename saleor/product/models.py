import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import HStoreField
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Max, Q
from django.urls import reverse
from django.utils.encoding import smart_text
from django.utils.text import slugify
from django.utils.translation import pgettext_lazy
from django_prices.models import Price, PriceField
from mptt.managers import TreeManager
from mptt.models import MPTTModel
from prices import PriceRange
from text_unidecode import unidecode
from versatileimagefield.fields import PPOIField, VersatileImageField

from saleor.easyship.api import post
from ..core.exceptions import InsufficientStock
from ..discount.utils import calculate_discounted_price
from .utils import get_attributes_display_map


class Category(MPTTModel):
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=50)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, related_name='children',
        on_delete=models.CASCADE)

    objects = models.Manager()
    tree = TreeManager()

    class Meta:
        app_label = 'product'
        permissions = (
            ('view_category',
             pgettext_lazy('Permission description', 'Can view categories')),
            ('edit_category',
             pgettext_lazy('Permission description', 'Can edit categories')))

    def __str__(self):
        return self.name

    def get_absolute_url(self, ancestors=None):
        return reverse('product:category',
                       kwargs={'path': self.get_full_path(ancestors),
                               'category_id': self.id})

    def get_full_path(self, ancestors=None):
        if not self.parent_id:
            return self.slug
        if not ancestors:
            ancestors = self.get_ancestors()
        nodes = [node for node in ancestors] + [self]
        return '/'.join([node.slug for node in nodes])

class ProductAdditionalInfo(models.Model):
    actual_weight = models.FloatField()
    height = models.FloatField()
    width = models.FloatField()
    length = models.FloatField()
    category = models.CharField(max_length=255)
    declared_currency = models.CharField(max_length=3)
    declared_customs_value= models.IntegerField(default=100)

    class Meta:
        app_label = 'product'

    def __str__(self):
        return self.actual_weight

    def __repr__(self):
        class_ = type(self)
        return '<%s.%s(pk=%r, weight=%r)>' % (
            class_.__module__, class_.__name__, self.pk, self.actual_weight)

class ProductType(models.Model):
    name = models.CharField(max_length=128)
    has_variants = models.BooleanField(default=True)
    product_attributes = models.ManyToManyField(
        'ProductAttribute', related_name='product_types', blank=True)
    variant_attributes = models.ManyToManyField(
        'ProductAttribute', related_name='product_variant_types', blank=True)
    is_shipping_required = models.BooleanField(default=False)

    class Meta:
        app_label = 'product'

    def __str__(self):
        return self.name

    def __repr__(self):
        class_ = type(self)
        return '<%s.%s(pk=%r, name=%r)>' % (
            class_.__module__, class_.__name__, self.pk, self.name)


class ProductQuerySet(models.QuerySet):
    def available_products(self):
        today = datetime.date.today()
        return self.filter(
            Q(available_on__lte=today) | Q(available_on__isnull=True),
            Q(is_published=True))


class Product(models.Model):
    # product_additional_info = models.ForeignKey(
    #     ProductAdditionalInfo, related_name='products', on_delete=models.CASCADE, null=True
    # )
    product_type = models.ForeignKey(
        ProductType, related_name='products', on_delete=models.CASCADE)
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField()
    category = models.ForeignKey(
        Category, related_name='products', on_delete=models.CASCADE)
    price = PriceField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12, decimal_places=2)
    available_on = models.DateField(blank=True, null=True)
    is_published = models.BooleanField(default=True)
    attributes = HStoreField(default={})
    updated_at = models.DateTimeField(auto_now=True, null=True)
    is_featured = models.BooleanField(default=False)

    # added
    actual_weight = models.FloatField(default=1.0)
    height = models.FloatField(default=1.0)
    width = models.FloatField(default=1.0)
    length = models.FloatField(default=1.0)
    # category = models.CharField(max_length=255, default="mobile")
    declared_currency = models.CharField(max_length=3, default="SGD",null=True, blank=True)
    declared_customs_value = models.IntegerField(default=100, null=True, blank=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        app_label = 'product'
        permissions = (
            ('view_product',
             pgettext_lazy('Permission description', 'Can view products')),
            ('edit_product',
             pgettext_lazy('Permission description', 'Can edit products')),
            ('view_properties',
             pgettext_lazy(
                 'Permission description', 'Can view product properties')),
            ('edit_properties',
             pgettext_lazy(
                 'Permission description', 'Can edit product properties')))

    def __iter__(self):
        if not hasattr(self, '__variants'):
            setattr(self, '__variants', self.variants.all())
        return iter(getattr(self, '__variants'))

    def __repr__(self):
        class_ = type(self)
        return '<%s.%s(pk=%r, name=%r)>' % (
            class_.__module__, class_.__name__, self.pk, self.name)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            'product:details',
            kwargs={'slug': self.get_slug(), 'product_id': self.id})

    def get_slug(self):
        return slugify(smart_text(unidecode(self.name)))

    def is_in_stock(self):
        return any(variant.is_in_stock() for variant in self)

    def is_available(self):
        today = datetime.date.today()
        return self.available_on is None or self.available_on <= today

    def get_first_image(self):
        first_image = self.images.first()
        return first_image.image if first_image else None

    def get_attribute(self, pk):
        return self.attributes.get(smart_text(pk))

    def set_attribute(self, pk, value_pk):
        self.attributes[smart_text(pk)] = smart_text(value_pk)

    def get_price_per_item(self, item, discounts=None):
        return item.get_price_per_item(discounts)

    def get_price_range(self, discounts=None):
        if self.variants.exists():
            prices = [
                self.get_price_per_item(variant, discounts=discounts)
                for variant in self]
            return PriceRange(min(prices), max(prices))
        price = calculate_discounted_price(self, self.price, discounts)
        return PriceRange(price, price)

    def get_gross_price_range(self, discounts=None):
        grosses = [
            self.get_price_per_item(variant, discounts=discounts)
            for variant in self]
        if not grosses:
            return None
        grosses = sorted(grosses, key=lambda x: x.tax)
        return PriceRange(min(grosses), max(grosses))

    def to_dict(self):
        return {
            "description": self.description[:200],
            "actual_weight": self.actual_weight,
            "height": self.height,
            "width": self.width,
            "length": self.length,
            # "category": self.category.name,
            # TODO: dm Long
            "category": "watches",
            # "category": self.category,
            "declared_currency": self.declared_currency,
            "declared_customs_value": self.declared_customs_value
        }

    def get_most_related_products(self, checkout):
        other_products = Product.objects.exclude(pk=self.pk).order_by('actual_weight')[:10]
        postal_code = checkout.__dict__['storage']['shipping_address']['postal_code']
        country_code = checkout.__dict__['storage']['shipping_address']['country']

        data = {
            "origin_country_alpha2": "SG",
            "origin_postal_code": "639778",
            "destination_country_alpha2": country_code,
            "destination_postal_code": postal_code,
            "taxes_duties_paid_by": "Sender",
            "is_insured": False
        }

        # for individual product
        data['items'] = [self.to_dict()]
        rates = post("rate/v1/rates", data).get('rates', [])
        criteria = sorted([(rate['shipment_charge_total'], rate['min_delivery_time']) for rate in rates])
        if len(criteria) == 1:
            criteria = [criteria[0][0], criteria[0][0], criteria[0][0]]
        elif len(criteria) == 2:
            criteria = [criteria[0][0], criteria[0][0], criteria[1][0]]
        else:
            criteria = [criteria[0][0], criteria[1][0], criteria[-1][0]]

        # for combining products
        increase = []
        for product in other_products:
            data['items'] = [self.to_dict(), product.to_dict()]
            combined_rates = post("rate/v1/rates", data).get('rates', [])
            combined_criteria = sorted([(combined_rate['shipment_charge_total'], combined_rate['min_delivery_time']) for combined_rate in combined_rates])
            if len(combined_criteria) == 1:
                combined_criteria = [combined_criteria[0][0], combined_criteria[0][0], combined_criteria[0][0]]
            elif len(criteria) == 2:
                combined_criteria = [combined_criteria[0][0], combined_criteria[0][0], combined_criteria[1][0]]
            else:
                combined_criteria = [combined_criteria[0][0], combined_criteria[1][0], combined_criteria[-1][0]]

            min_increase = min(combined_criteria[2] - criteria[2], combined_criteria[1] - criteria[1], combined_criteria[0] - criteria[0])
            increase.append((min_increase, product.pk))
        increase = sorted(increase)
        return [p for p in increase[:3]]

class ProductVariant(models.Model):
    sku = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100, blank=True)
    price_override = PriceField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12, decimal_places=2,
        blank=True, null=True)
    product = models.ForeignKey(
        Product, related_name='variants', on_delete=models.CASCADE)
    attributes = HStoreField(default={})
    images = models.ManyToManyField('ProductImage', through='VariantImage')

    class Meta:
        app_label = 'product'

    def __str__(self):
        return self.name or self.display_variant_attributes()

    def check_quantity(self, quantity):
        total_available_quantity = self.get_stock_quantity()
        if quantity > total_available_quantity:
            raise InsufficientStock(self)

    def get_stock_quantity(self):
        return sum([stock.quantity_available for stock in self.stock.all()])

    def get_price_per_item(self, discounts=None):
        price = self.price_override or self.product.price
        price = calculate_discounted_price(self.product, price, discounts)
        return price

    def get_absolute_url(self):
        slug = self.product.get_slug()
        product_id = self.product.id
        return reverse('product:details',
                       kwargs={'slug': slug, 'product_id': product_id})

    def as_data(self):
        return {
            'product_name': str(self),
            'product_id': self.product.pk,
            'variant_id': self.pk,
            'unit_price': str(self.get_price_per_item().gross)}

    def is_shipping_required(self):
        return self.product.product_type.is_shipping_required

    def is_in_stock(self):
        return any(
            [stock.quantity_available > 0 for stock in self.stock.all()])

    def get_attribute(self, pk):
        return self.attributes.get(smart_text(pk))

    def set_attribute(self, pk, value_pk):
        self.attributes[smart_text(pk)] = smart_text(value_pk)

    def display_variant_attributes(self, attributes=None):
        if attributes is None:
            attributes = self.product.product_type.variant_attributes.all()
        values = get_attributes_display_map(self, attributes)
        if values:
            return ', '.join(
                ['%s: %s' % (smart_text(attributes.get(id=int(key))),
                             smart_text(value))
                 for (key, value) in values.items()])
        return ''

    def display_product(self):
        variant_display = str(self)
        product_display = (
            '%s (%s)' % (self.product, variant_display)
            if variant_display else str(self.product))
        return smart_text(product_display)

    def get_first_image(self):
        return self.product.get_first_image()

    def select_stockrecord(self, quantity=1):
        # By default selects stock with lowest cost price. If stock cost price
        # is None we assume price equal to zero to allow sorting.
        stock = [
            stock_item for stock_item in self.stock.all()
            if stock_item.quantity_available >= quantity]
        zero_price = Price(0, currency=settings.DEFAULT_CURRENCY)
        stock = sorted(
            stock, key=(lambda s: s.cost_price or zero_price), reverse=False)
        if stock:
            return stock[0]
        return None

    def get_cost_price(self):
        stock = self.select_stockrecord()
        if stock:
            return stock.cost_price
        return None


class StockLocation(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        permissions = (
            ('view_stock_location',
             pgettext_lazy('Permission description',
                           'Can view stock location')),
            ('edit_stock_location',
             pgettext_lazy('Permission description',
                           'Can edit stock location')))

    def __str__(self):
        return self.name


class Stock(models.Model):
    variant = models.ForeignKey(
        ProductVariant, related_name='stock', on_delete=models.CASCADE)
    location = models.ForeignKey(
        StockLocation, null=True, on_delete=models.CASCADE)
    quantity = models.IntegerField(
        validators=[MinValueValidator(0)], default=Decimal(1))
    quantity_allocated = models.IntegerField(
        validators=[MinValueValidator(0)], default=Decimal(0))
    cost_price = PriceField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12, decimal_places=2,
        blank=True, null=True)

    class Meta:
        app_label = 'product'
        unique_together = ('variant', 'location')

    def __str__(self):
        return '%s - %s' % (self.variant.name, self.location)

    @property
    def quantity_available(self):
        return max(self.quantity - self.quantity_allocated, 0)


class ProductAttribute(models.Model):
    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ('slug', )

    def __str__(self):
        return self.name

    def get_formfield_name(self):
        return slugify('attribute-%s' % self.slug, allow_unicode=True)

    def has_values(self):
        return self.values.exists()


class AttributeChoiceValue(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    color = models.CharField(
        max_length=7, blank=True,
        validators=[RegexValidator('^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')])
    attribute = models.ForeignKey(
        ProductAttribute, related_name='values', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('name', 'attribute')

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, related_name='images', on_delete=models.CASCADE)
    image = VersatileImageField(
        upload_to='products', ppoi_field='ppoi', blank=False)
    ppoi = PPOIField()
    alt = models.CharField(max_length=128, blank=True)
    order = models.PositiveIntegerField(editable=False)

    class Meta:
        ordering = ('order', )
        app_label = 'product'

    def get_ordering_queryset(self):
        return self.product.images.all()

    def save(self, *args, **kwargs):
        if self.order is None:
            qs = self.get_ordering_queryset()
            existing_max = qs.aggregate(Max('order'))
            existing_max = existing_max.get('order__max')
            self.order = 0 if existing_max is None else existing_max + 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        qs = self.get_ordering_queryset()
        qs.filter(order__gt=self.order).update(order=F('order') - 1)
        super().delete(*args, **kwargs)


class VariantImage(models.Model):
    variant = models.ForeignKey(
        'ProductVariant', related_name='variant_images',
        on_delete=models.CASCADE)
    image = models.ForeignKey(
        ProductImage, related_name='variant_images', on_delete=models.CASCADE)


class Collection(models.Model):
    name = models.CharField(max_length=128, unique=True)
    slug = models.SlugField(max_length=255)
    products = models.ManyToManyField(
        Product, blank=True, related_name='collections')

    class Meta:
        ordering = ['pk']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            'product:collection',
            kwargs={'pk': self.id, 'slug': self.slug})
