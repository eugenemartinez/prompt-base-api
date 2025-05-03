import re # Add this import
from rest_framework import serializers
from .models import Prompt, Comment
from .validators import validate_tags

class CommentSerializer(serializers.ModelSerializer):
    # Make username read-only in the API representation after creation
    username = serializers.CharField(max_length=50, required=False, allow_blank=True, read_only=True)
    # Modification code should not be sent in responses, only potentially received for updates/deletes (handled in views)
    modification_code = serializers.CharField(max_length=8, write_only=True, required=False) # write_only hides it from response

    class Meta:
        model = Comment
        fields = [
            'comment_id',
            'prompt', # Usually sent as ID, but read_only prevents requiring it on create within prompt
            'content',
            'username',
            'modification_code', # Included for potential validation, but write_only
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'comment_id',
            'prompt', # Prevent changing the associated prompt
            'created_at',
            'updated_at',
            # username is handled specifically above to allow on create but not update via serializer directly
        ]

    # Override create to handle optional username (generation is in model.save)
    def create(self, validated_data):
        # Username generation is handled by the model's save method
        return Comment.objects.create(**validated_data)


class PromptSerializer(serializers.ModelSerializer):
    # Make username read-only in the API representation after creation
    username = serializers.CharField(max_length=50, required=False, allow_blank=True, read_only=True)
    # Modification code should not be sent in responses, only potentially received for updates/deletes (handled in views)
    modification_code = serializers.CharField(max_length=8, write_only=True, required=False) # write_only hides it from response
    # Include comments when retrieving a single prompt, but make it read-only
    # Use a nested serializer for comments
    comments = CommentSerializer(many=True, read_only=True) # Use the CommentSerializer defined above

    class Meta:
        model = Prompt
        fields = [
            'prompt_id',
            'title',
            'content',
            'username',
            'tags',
            'modification_code', # Included for potential validation, but write_only
            'created_at',
            'updated_at',
            'comments', # Add the nested comments field
        ]
        read_only_fields = [
            'prompt_id',
            'created_at',
            'updated_at',
            # username is handled specifically above
            'comments', # Comments are read-only in the prompt representation
        ]
        # Add extra validation for tags if needed beyond the model validator
        # extra_kwargs = {
        #     'tags': {'validators': [validate_tags]}
        # }

    # Override create to handle optional username (generation is in model.save)
    def create(self, validated_data):
        # Username generation is handled by the model's save method
        return Prompt.objects.create(**validated_data)

    # Optional: Add custom validation for tags array length/content if not fully covered by model
    def validate_tags(self, value):
        if not value: # Allow empty list
            return value
        if len(value) > 10:
            raise serializers.ValidationError("Maximum of 10 tags allowed.")
        # Add regex/length check per tag if model validator isn't sufficient for API level
        tag_regex = r'^[a-zA-Z0-9-]+$'
        for tag in value:
            if len(tag) > 30:
                 raise serializers.ValidationError(f"Tag '{tag}' exceeds 30 characters.")
            if not re.match(tag_regex, tag): # Use re.match here
                 raise serializers.ValidationError(f"Tag '{tag}' contains invalid characters. Use only letters, numbers, and hyphens.")
        return value


class PromptListSerializer(PromptSerializer):
    """
    Serializer for the list view, excluding comments for brevity.
    Inherits from PromptSerializer but overrides the fields.
    """
    class Meta(PromptSerializer.Meta): # Inherit Meta from PromptSerializer
         fields = [
            'prompt_id',
            'title',
            'content', # Consider truncating content for list view if needed
            'username',
            'tags',
            # Exclude modification_code
            'created_at',
            'updated_at',
            # Exclude comments field
        ]
         read_only_fields = [
            'prompt_id',
            'username',
            'created_at',
            'updated_at',
        ]


# Serializer specifically for receiving batch IDs
class PromptBatchIdSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False
    )