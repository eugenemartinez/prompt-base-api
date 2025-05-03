import re
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

def validate_tags(tags):
    """Validator for the tags array field (used in Model and potentially Serializer)."""
    if not isinstance(tags, list):
         # This check might be redundant if ArrayField handles it, but good practice
         raise ValidationError(_('Tags must be provided as a list.'))

    if len(tags) > 10:
        raise ValidationError(_('Maximum of 10 tags allowed.'))

    tag_regex_validator = RegexValidator(
        r'^[a-zA-Z0-9-]+$',
        _('Tags can only contain letters, numbers, and hyphens.')
    )

    for tag in tags:
        if not isinstance(tag, str):
             raise ValidationError(_('Each tag must be a string.'))
        if len(tag) > 30:
            raise ValidationError(_(f"Tag '{tag}' exceeds 30 characters."))
        if not tag:
             raise ValidationError(_('Tags cannot be empty strings.'))
        tag_regex_validator(tag) # Validate individual tag format