# backend/catalog/forms.py

from django import forms
from django.utils import timezone

from .models import Product


class ProductForm(forms.ModelForm):
    """
    Producer-facing form for TC-003 (Add New Product).

    Ensures:
    - Required fields are present
    - Price > 0
    - Stock is non-negative (PositiveIntegerField already enforces)
    - Harvest date defaults to today if not provided (matches test case "current date")
    - Allergen input is normalized (comma-separated string)
    - Form fields render with consistent CSS classes (no template filters needed)
    """

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "description",
            "price",
            "unit",
            "availability",
            "stock_quantity",
            "allergens",
            "harvest_date",
            "image",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Organic Free Range Eggs",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
            "unit": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Dozen, kg, Jar",
                }
            ),
            "availability": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "stock_quantity": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 0,
                }
            ),
            "allergens": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., eggs, milk (leave blank if none)",
                }
            ),
            "harvest_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "image": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None:
            raise forms.ValidationError("Price is required.")
        if price <= 0:
            raise forms.ValidationError("Price must be greater than 0.")
        return price

    def clean_allergens(self):
        """
        Normalise allergens to a simple comma-separated list:
        - trims whitespace
        - collapses multiple commas/spaces
        - lowercases for consistency (optional, but helpful)
        """
        raw = self.cleaned_data.get("allergens", "") or ""
        # Split by commas, trim, drop empties
        parts = [p.strip() for p in raw.split(",")]
        parts = [p for p in parts if p]
        # You can remove .lower() if your team wants original casing
        parts = [p.lower() for p in parts]
        return ", ".join(parts)

    def clean_harvest_date(self):
        harvest_date = self.cleaned_data.get("harvest_date")
        if harvest_date is None:
            # TC-003 uses "current date" — default to today if user leaves it blank
            return timezone.localdate()
        if harvest_date > timezone.localdate():
            raise forms.ValidationError("Harvest date cannot be in the future.")
        return harvest_date

    def clean(self):
        """
        Cross-field validation.
        """
        cleaned = super().clean()
        availability = cleaned.get("availability")
        stock_qty = cleaned.get("stock_quantity")

        # Keep this aligned with Product.clean() rule:
        if availability == Product.Availability.AVAILABLE and stock_qty == 0:
            self.add_error(
                "stock_quantity",
                "Available products should have stock greater than 0.",
            )

        return cleaned