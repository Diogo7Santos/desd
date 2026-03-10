from django import forms
from django.contrib.auth import get_user_model
from .models import CustomerProfile

User = get_user_model()


ROLE_CHOICES = (
    (User.Role.CUSTOMER, "Customer"),
    (User.Role.PRODUCER, "Producer"),
    (User.Role.ADMIN, "Admin"),
)


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"})
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)


class RegisterForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-input"})
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"})
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"})
    )

    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)

    # Producer fields
    business_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    contact_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    producer_postcode = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )

    # Customer fields
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

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "Passwords do not match.")

        role = cleaned.get("role")

        if role == User.Role.PRODUCER:
            for field in ["business_name", "contact_name", "producer_postcode"]:
                if not cleaned.get(field):
                    self.add_error(field, "This field is required for producers.")

        if role == User.Role.CUSTOMER:
            for field in ["customer_type_id", "line_1", "city", "customer_postcode"]:
                if not cleaned.get(field):
                    self.add_error(field, "This field is required for customers.")

        return cleaned