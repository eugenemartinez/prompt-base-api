import re
import bleach
from rest_framework import serializers
from .models import Prompt, Comment
from .validators import validate_tags

# --- Define allowed HTML (optional, empty means strip all) ---
# If you wanted to allow specific safe tags like bold/italic:
# ALLOWED_TAGS = ['b', 'i', 'strong', 'em']
# ALLOWED_ATTRIBUTES = {} # No attributes allowed
# For this project, stripping all HTML is likely safest:
ALLOWED_TAGS = []
ALLOWED_ATTRIBUTES = {}
# --- End Define ---


class CommentSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        allow_null=True
    )
    modification_code = serializers.CharField(max_length=8, write_only=True, required=False)

    class Meta:
        model = Comment
        fields = [
            'comment_id', 'prompt', 'content', 'username', 'modification_code',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'comment_id', 'prompt', 'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        return Comment.objects.create(**validated_data)

    # --- Add bleach validation for content ---
    def validate_content(self, value):
        """Strip HTML tags from comment content."""
        cleaned_value = bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
        return cleaned_value
    # --- End Add ---


class PromptSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        allow_null=True
    )
    modification_code = serializers.CharField(max_length=8, write_only=True, required=False)
    # Use CommentSerializer for nested representation, but make it read-only
    # as comments are managed via their own endpoint.
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Prompt
        fields = [
            'prompt_id', 'title', 'content', 'username', 'tags',
            'modification_code', 'created_at', 'updated_at', 'comments',
        ]
        read_only_fields = [
            'prompt_id', 'created_at', 'updated_at', 'comments',
        ]

    def create(self, validated_data):
        return Prompt.objects.create(**validated_data)

    # --- Add bleach validation for title and content ---
    def validate_title(self, value):
        """Strip HTML tags from prompt title."""
        cleaned_value = bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
        # Optional: Add extra validation after cleaning if needed
        if not cleaned_value:
             raise serializers.ValidationError("Title cannot be empty after HTML stripping.")
        return cleaned_value

    def validate_content(self, value):
        """Strip HTML tags from prompt content."""
        cleaned_value = bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
        # Optional: Add extra validation after cleaning if needed
        if not cleaned_value:
             raise serializers.ValidationError("Content cannot be empty after HTML stripping.")
        return cleaned_value
    # --- End Add ---

    def validate_tags(self, value):
        if not value:
            # Allow empty list if tags are optional (which they are based on model)
            return [] # Return empty list explicitly
        if len(value) > 10:
            raise serializers.ValidationError("Maximum of 10 tags allowed.")

        tag_regex = r'^[a-zA-Z0-9-]+$'
        processed_tags = set() # Use a set for efficient duplicate checking (case-insensitive)
        final_tags = [] # Keep the original case for storing, if desired

        for tag in value:
            # 1. Strip leading/trailing whitespace
            stripped_tag = tag.strip()

            # 2. Skip if empty after stripping
            if not stripped_tag:
                continue

            # 3. Check length BEFORE regex
            if len(stripped_tag) > 30:
                 raise serializers.ValidationError(f"Tag '{stripped_tag}' exceeds 30 characters.")

            # 4. Validate format using regex on the stripped tag
            #    DO NOT remove invalid characters; reject the tag instead.
            if not re.match(tag_regex, stripped_tag):
                 raise serializers.ValidationError(
                     f"Tag '{stripped_tag}' contains invalid characters. Use only letters, numbers, and hyphens."
                 )

            # 5. Check for duplicates (case-insensitive)
            lower_case_tag = stripped_tag.lower()
            if lower_case_tag in processed_tags:
                # Remove or comment out the 'continue' line:
                # continue # Silently ignore duplicates

                # Uncomment or add the raise ValidationError line:
                raise serializers.ValidationError(f"Duplicate tag found (case-insensitive): '{stripped_tag}'")
            else:
                processed_tags.add(lower_case_tag)
                final_tags.append(stripped_tag) # Add the original (or lower_case_tag if you prefer)

        # Optional: Check if any tags remain after cleaning/deduplication
        # if not final_tags and value: # If input had tags but none survived
        #     raise serializers.ValidationError("No valid tags provided after cleaning.")

        return final_tags # Return the cleaned, deduplicated list


# --- Update PromptListSerializer (Minimal Change for comment_count) ---
class PromptListSerializer(PromptSerializer):
    username = serializers.CharField(read_only=True) # Keep existing override
    # Add the comment_count field
    comment_count = serializers.IntegerField(read_only=True) # <--- Add ONLY this field definition

    class Meta(PromptSerializer.Meta): # Inherit Meta
         # Add 'comment_count' to the existing fields list
         fields = [
            'prompt_id', 'title', 'content', 'username', 'tags',
            'created_at', 'updated_at',
            'comment_count', # <--- Add comment_count here
        ]
         # Add 'comment_count' to the existing read_only_fields list
         read_only_fields = [
            'prompt_id', 'username', 'created_at', 'updated_at',
            'comment_count', # <--- Add comment_count here
            # Note: 'tags' was not in your original read_only_fields, so keep it that way
        ]
# --- End Update ---


class PromptBatchIdSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.CharField(), # <-- Accept any string initially
        allow_empty=True              # <-- Allow empty lists []
    )