from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import CustomerProfile

User = get_user_model()

LOGIN_ROLE_CHOICES = (
    (User.Role.CUSTOMER, "Customer"),
    (User.Role.PRODUCER, "Producer"),
    (User.Role.ADMIN, "Admin"),
)

REGISTER_ROLE_CHOICES = (
    (User.Role.CUSTOMER, "Customer"),
    (User.Role.PRODUCER, "Producer"),
)


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-input"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"})
    )
    role = forms.ChoiceField(choices=LOGIN_ROLE_CHOICES, widget=forms.RadioSelect)
    remember_me = forms.BooleanField(required=False)


class RegisterForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-input"})
    )
    phone = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"})
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"})
    )

    role = forms.ChoiceField(choices=REGISTER_ROLE_CHOICES, widget=forms.RadioSelect)

    # Producer fields
    business_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    contact_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    business_address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    producer_postcode = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )

    # Customer fields
    full_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    customer_type_id = forms.ChoiceField(
        required=False,
        choices=CustomerProfile.CustomerType.choices,
        widget=forms.RadioSelect,
    )
    line_1 = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    line_2 = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    customer_postcode = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    accept_terms = forms.BooleanField(required=False)

    def clean(self):
        cleaned = super().clean()

        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        if password1:
            try:
                validate_password(password1)
            except ValidationError as exc:
                self.add_error("password1", exc)

        role = cleaned.get("role")

        if role == User.Role.PRODUCER:
            for field in ["business_name", "contact_name", "business_address", "producer_postcode"]:
                if not cleaned.get(field):
                    self.add_error(field, "This field is required for producers.")

        if role == User.Role.CUSTOMER:
            for field in ["full_name", "customer_type_id", "line_1", "city", "customer_postcode"]:
                if not cleaned.get(field):
                    self.add_error(field, "This field is required for customers.")
            if not cleaned.get("accept_terms"):
                self.add_error("accept_terms", "You must accept the terms and conditions.")

        return cleaned