# backend/catalog/urls.py

from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    # Customer-facing catalog browsing
    path("", views.product_list, name="product_list"),
    path("category/<slug:category>/", views.category_list, name="category_list"),
    path("search/", views.product_search, name="product_search"),

    # Producer product management
    path("producer/products/", views.producer_products, name="producer_products"),
    path("product/add/", views.product_create, name="product_create"),
    path("product/<int:pk>/edit/", views.product_update, name="product_update"),

    # Product details
    path("product/<int:pk>/", views.product_detail, name="product_detail"),
]