from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db.models import CharField
from django.db.models import IntegerField
from django.db.models import Sum
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Default custom user model for Tabdeal Task.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    credit = IntegerField(
        _("Credit"),
        default=0,
        validators=[MinValueValidator(0)],
    )
    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})

    def get_balance(self) -> str:
        """Get user's balance.

        Returns:
            str: User's balance.

        """
        return self.transactions.aggregate(balance=Sum("amount"))["balance"] or 0
