from django.urls import path
from . import views

urlpatterns = [

    # Home
    path("", views.home, name="home"),

    # Authentication
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Dashboard
    path("dashboard/", views.dashboard, name="dashboard"),

    # Profile
    path("profile/", views.profile_view, name="profile"),
    path("change-password/", views.change_password, name="change_password"),

    # Products & browsing
    path("products/", views.product_list, name="product_list"),
    path("products/<int:product_id>/", views.product_detail, name="product_detail"),

    # Cart
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/remove/<int:item_id>/", views.remove_from_cart, name="remove_from_cart"),
    path("cart/update/<int:item_id>/", views.update_cart_item, name="update_cart_item"),

    # Orders (customer)
    path("orders/", views.my_orders, name="my_orders"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/reorder/", views.reorder, name="reorder"),

    # Producer dashboard
    path("producer/products/", views.producer_products, name="producer_products"),
    path("producer/orders/", views.producer_orders, name="producer_orders"),
    path("producer/settlements/", views.producer_settlements, name="producer_settlements"),

    # Admin reports
    path("admin/commission-reports/", views.admin_commission_reports, name="admin_commission_reports"),

    # Error page
    path("error/", views.error_page, name="error_page"),
]
