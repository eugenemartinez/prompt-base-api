import uuid
import secrets
import random
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxLengthValidator, MinLengthValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# --- Helper Functions ---

def generate_modification_code():
    """Generates an 8-character hex string."""
    return secrets.token_hex(4)

def generate_username():
    """Generates a random adjective-noun username."""
    # Define lists (can be expanded or moved to settings/constants)
    adjectives = ["quick", "lazy", "sleepy", "noisy", "hungry", "cool", "brave", "clever", "shiny", "wise"]
    nouns = ["fox", "dog", "cat", "mouse", "bear", "lion", "tiger", "frog", "bird", "wolf"]
    return f"{random.choice(adjectives)}-{random.choice(nouns)}"

def validate_tags(tags):
    """Validator for the tags array field."""
    if len(tags) > 10:
        raise ValidationError(_('Maximum of 10 tags allowed.'))
    tag_regex = RegexValidator(r'^[a-zA-Z0-9-]+$', _('Tags can only contain letters, numbers, and hyphens.'))
    for tag in tags:
        if len(tag) > 30:
            raise ValidationError(_('Each tag must be 30 characters or less.'))
        tag_regex(tag) # Validate individual tag format

# --- Models ---

class Prompt(models.Model):
    prompt_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150, blank=False, null=False)
    content = models.TextField(max_length=15000, blank=False, null=False)
    username = models.CharField(max_length=50, blank=True, null=True, editable=False) # editable=False makes it non-updatable via ModelForms/Admin
    tags = ArrayField(
        models.CharField(max_length=30),
        size=10,
        blank=True,
        null=True,
        validators=[validate_tags] # Custom validator for array content
    )
    modification_code = models.CharField(
        max_length=8,
        blank=True, # Generated on save
        editable=False,
        validators=[MinLengthValidator(8)] # Ensure it's always 8 chars if set
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        is_new = self._state.adding # Use this to check if it's a new instance

        # Generate username if blank on first save (when is_new is True)
        if is_new and not self.username:
            self.username = generate_username()
            if len(self.username) > 50:
                 self.username = self.username[:50]

        # Generate modification code on first save (when is_new is True)
        if is_new: # No need to check if self.modification_code exists, always generate for new
            self.modification_code = generate_modification_code()

        # Prevent username update after creation
        if not is_new: # Only run this block if it's an UPDATE (not new)
            try:
                # Fetch the original state from the database
                original = Prompt.objects.get(pk=self.pk)
                if original.username != self.username:
                     # Reset username if it was changed during update
                     self.username = original.username
            except Prompt.DoesNotExist:
                # This case should ideally not happen during an update, but handle defensively
                pass

        super().save(*args, **kwargs) # Call the "real" save() method.

    def __str__(self):
        return self.title

class Comment(models.Model):
    comment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt = models.ForeignKey(Prompt, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField(max_length=2000, blank=False, null=False)
    username = models.CharField(max_length=50, blank=True, null=True, editable=False)
    modification_code = models.CharField(
        max_length=8,
        blank=True,
        editable=False,
        validators=[MinLengthValidator(8)]
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        is_new = self._state.adding # Use this to check if it's a new instance

        # Generate username if blank on first save
        if is_new and not self.username:
            self.username = generate_username()
            if len(self.username) > 50:
                 self.username = self.username[:50]

        # Generate modification code on first save
        if is_new:
            self.modification_code = generate_modification_code()

        # Prevent username update after creation
        if not is_new: # Only run this block if it's an UPDATE
            try:
                original = Comment.objects.get(pk=self.pk)
                if original.username != self.username:
                     self.username = original.username
            except Comment.DoesNotExist:
                pass

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Comment on '{self.prompt.title}' by {self.username or 'Anonymous'}"

    class Meta:
        ordering = ['-created_at'] # Default ordering for comments (newest first)
