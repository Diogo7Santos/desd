from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


ROLE_CHOICES = (
    (User.Role.CUSTOMER, "Customer"),
    (User.Role.PRODUCER, "Producer"),
    (User.Role.ADMIN, "Admin"),
)


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-input"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-input"}))
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)

class RegisterForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-input"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-input"}))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-input"}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-input"}))
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned