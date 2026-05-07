from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import ProducerProfile, CustomerProfile, Address
from .postcodes import (
    clean_uk_postcode,
    POSTCODE_ERROR_MESSAGE,
)

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
    organisation_name = forms.CharField(
    required=False,
    widget=forms.TextInput(attrs={"class": "form-input"})
    )
    contact_person = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    is_charity_or_education = forms.BooleanField(required=False)
    default_delivery_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-input", "rows": 3})
    )

    def clean_producer_postcode(self):
        return clean_uk_postcode(self.cleaned_data.get("producer_postcode", ""))

    def clean_customer_postcode(self):
        return clean_uk_postcode(self.cleaned_data.get("customer_postcode", ""))

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

            customer_type = cleaned.get("customer_type_id")

            if str(customer_type) == str(CustomerProfile.CustomerType.RESTAURANT):
                for field in ["organisation_name", "contact_person"]:
                    if not cleaned.get(field):
                        self.add_error(field, "This field is required for restaurant accounts.")

            if str(customer_type) == str(CustomerProfile.CustomerType.COMMUNITY_GROUP):
                for field in ["organisation_name", "contact_person"]:
                    if not cleaned.get(field):
                        self.add_error(field, "This field is required for community group accounts.")

            if str(customer_type) == str(CustomerProfile.CustomerType.YOUNG_PROFESSIONAL):
                if not cleaned.get("contact_person"):
                    self.add_error("contact_person", "This field is required for young professional accounts.")
                    
            if str(customer_type) == str(CustomerProfile.CustomerType.FAMILIES):
                if not cleaned.get("contact_person"):
                    self.add_error("contact_person", "This field is required for families accounts.")
        return cleaned


# Additional forms for account management
class UserAccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email", "phone"]
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Email already registered.")
        return email


class ProducerAccountForm(forms.ModelForm):
    class Meta:
        model = ProducerProfile
        fields = ["business_name", "contact_name", "business_address", "postcode"]
        widgets = {
            "business_name": forms.TextInput(attrs={"class": "form-input"}),
            "contact_name": forms.TextInput(attrs={"class": "form-input"}),
            "business_address": forms.TextInput(attrs={"class": "form-input"}),
            "postcode": forms.TextInput(attrs={"class": "form-input"}),
        }

    def clean_postcode(self):
        return clean_uk_postcode(self.cleaned_data.get("postcode", ""))


class CustomerAccountForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = [
            "customer_type_id",
            "organisation_name",
            "contact_person",
            "is_charity_or_education",
            "default_delivery_instructions",
        ]
        widgets = {
            "customer_type_id": forms.RadioSelect(),
            "organisation_name": forms.TextInput(attrs={"class": "form-input"}),
            "contact_person": forms.TextInput(attrs={"class": "form-input"}),
            "default_delivery_instructions": forms.Textarea(
                attrs={"class": "form-input", "rows": 3}
            ),
        }


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ["line_1", "line_2", "city", "postcode"]
        widgets = {
            "line_1": forms.TextInput(attrs={"class": "form-input"}),
            "line_2": forms.TextInput(attrs={"class": "form-input"}),
            "city": forms.TextInput(attrs={"class": "form-input"}),
            "postcode": forms.TextInput(attrs={"class": "form-input"}),
        }

    def clean_postcode(self):
        return clean_uk_postcode(self.cleaned_data.get("postcode", ""))
