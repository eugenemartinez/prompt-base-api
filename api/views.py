from django.shortcuts import render
from rest_framework import generics, status, views # Import DRF components
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from django.shortcuts import get_object_or_404
from django.db.models import Q # For search queries
import random
from django.db import connection
from django.db.utils import OperationalError
from django.utils.decorators import method_decorator

# Import models and serializers
from .models import Prompt, Comment
from .serializers import (
    PromptSerializer,
    PromptListSerializer,
    CommentSerializer,
    PromptBatchIdSerializer
)

# Import pagination and filtering if needed later
# from rest_framework.pagination import PageNumberPagination
# from rest_framework import filters

# Import rate limiting decorators
from django_ratelimit.decorators import ratelimit

# --- Custom Pagination (Optional but Recommended) ---
# You can define a custom pagination class if you want different page sizes
# from rest_framework.pagination import PageNumberPagination
# class StandardResultsSetPagination(PageNumberPagination):
#     page_size = 10
#     page_size_query_param = 'limit' # Allow client to set page size via ?limit=
#     max_page_size = 100

# --- Prompt Views ---

# Apply decorator to dispatch for CBVs
@method_decorator(ratelimit(key='ip', rate='50/d', method='POST', block=True), name='dispatch')
class PromptListCreateView(generics.ListCreateAPIView):
    """
    GET /api/prompts/ : List all prompts (paginated, searchable, filterable by tags, sortable)
    POST /api/prompts/: Create a new prompt
    """
    queryset = Prompt.objects.all().order_by('-updated_at') # Default sort
    # pagination_class = StandardResultsSetPagination # Uncomment if using custom pagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PromptSerializer # Use full serializer for create (includes modification_code write_only)
        return PromptListSerializer # Use lighter serializer for list view

    # Remove decorator from post
    def post(self, request, *args, **kwargs):
        # Remove the manual check, decorator on dispatch handles it
        # was_limited = getattr(request, 'limited', False)
        # if was_limited:
        #     return Response({"detail": "Rate limit exceeded. Please try again later."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        # The model's save() method handles username/code generation
        serializer.save()
        # Note: The full PromptSerializer used for POST will return the complete object,
        # BUT modification_code is write_only, so it won't be in the response JSON.
        # We need to explicitly add it back for the initial creation response.
        instance = serializer.instance
        # Manually create response data to include the code
        response_data = PromptSerializer(instance).data # Serialize again to get default fields
        response_data['modification_code'] = instance.modification_code # Add the code
        # We need to return a Response here, but perform_create doesn't return.
        # The actual response is constructed in the parent 'create' method.
        # We'll adjust the 'create' method in the superclass or override 'create' fully if needed.
        # For now, let's rely on the PRD flow where frontend handles the code display separately.

    def get_queryset(self):
        """Optionally filter and sort the queryset."""
        queryset = super().get_queryset()
        search_query = self.request.query_params.get('search', None)
        tags_query = self.request.query_params.get('tags', None)
        sort_query = self.request.query_params.get('sort', None) # e.g., 'title_asc', 'updated_at_desc'

        # Search
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) | Q(content__icontains=search_query)
            )

        # Filter by Tags (assuming comma-separated tags like "tag1,tag2")
        if tags_query:
            tags_list = [tag.strip() for tag in tags_query.split(',') if tag.strip()]
            if tags_list:
                # Use __contains for simple array containment (requires GIN index for performance)
                # Or __overlap if you want prompts containing ANY of the tags
                queryset = queryset.filter(tags__contains=tags_list) # Check if array contains ALL tags
                # queryset = queryset.filter(tags__overlap=tags_list) # Check if array contains ANY tags

        # Sort
        if sort_query:
            sort_map = {
                'title_asc': 'title',
                'title_desc': '-title',
                'updated_at_asc': 'updated_at',
                'updated_at_desc': '-updated_at',
                # Add created_at if needed
            }
            sort_field = sort_map.get(sort_query.lower(), '-updated_at') # Default sort
            queryset = queryset.order_by(sort_field)

        return queryset


class PromptDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/prompts/:promptid/ : Retrieve a single prompt (with comments)
    PUT    /api/prompts/:promptid/ : Update a prompt (requires modification_code)
    PATCH  /api/prompts/:promptid/ : Partially update a prompt (requires modification_code)
    DELETE /api/prompts/:promptid/ : Delete a prompt (requires modification_code)
    """
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer # Use the full serializer with nested comments
    lookup_field = 'prompt_id' # Use UUID field for lookup

    def check_modification_code(self, request, instance):
        """Helper to check modification code from request body."""
        code = request.data.get('modification_code')
        if not code:
            raise PermissionDenied("Modification code is required.")
        if code != instance.modification_code:
            raise PermissionDenied("Invalid modification code.")
        return True # Code is valid

    # Remove decorators from put, patch, delete
    def put(self, request, *args, **kwargs):
        # Remove the manual check
        instance = self.get_object()
        self.check_modification_code(request, instance)
        # Prevent username update via PUT
        if 'username' in request.data:
             request.data.pop('username') # Or handle more gracefully
        return super().update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        # Remove the manual check
        instance = self.get_object()
        self.check_modification_code(request, instance)
        # Prevent username update via PATCH
        if 'username' in request.data:
             request.data.pop('username')
        return super().partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        # Remove the manual check
        instance = self.get_object()
        try:
            self.check_modification_code(request, instance)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # Override retrieve to handle pagination for nested comments if needed
    # (By default, PromptSerializer includes ALL comments)
    # We need to implement the PRD requirement: GET /api/prompts/:promptid returns only the FIRST page of comments.
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Get the first page of comments (e.g., 10)
        # Note: Default ordering is already set in Comment model Meta
        comments_queryset = instance.comments.all()[:10] # Simple slicing for first page
        # Manually serialize comments for the first page
        comment_serializer = CommentSerializer(comments_queryset, many=True)

        # Serialize the prompt instance itself
        prompt_serializer = self.get_serializer(instance)
        prompt_data = prompt_serializer.data

        # Replace the 'comments' field in the prompt data with the paginated comments
        prompt_data['comments'] = comment_serializer.data

        # Add pagination metadata for comments
        total_comments = instance.comments.count()
        prompt_data['comment_pagination'] = {
            'total_count': total_comments,
            'page_size': 10, # The size we fetched
            'has_more': total_comments > 10
        }

        return Response(prompt_data)


# --- Comment Views ---

# Apply decorator to dispatch for CBVs
@method_decorator(ratelimit(key='ip', rate='50/d', method='POST', block=True), name='dispatch')
class CommentListCreateView(generics.ListCreateAPIView):
    """
    GET /api/prompts/:promptid/comments : List comments for a specific prompt (paginated)
    POST /api/prompts/:promptid/comments: Create a new comment for a prompt
    """
    serializer_class = CommentSerializer
    # pagination_class = StandardResultsSetPagination # Uncomment if using custom pagination

    def get_queryset(self):
        """Filter comments by the prompt_id from the URL."""
        prompt_id = self.kwargs.get('prompt_id')
        # Ensure the prompt exists before trying to list comments
        get_object_or_404(Prompt, prompt_id=prompt_id)
        # Order by created_at ascending to show oldest first in list? Or keep default descending?
        # PRD says descending (newest first) by default. Model Meta handles this.
        return Comment.objects.filter(prompt_id=prompt_id) # .order_by('created_at')

    # Remove decorator from post
    def post(self, request, *args, **kwargs):
        # Remove the manual check
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Associate the comment with the prompt_id from the URL."""
        prompt_id = self.kwargs.get('prompt_id')
        prompt = get_object_or_404(Prompt, prompt_id=prompt_id)
        # The model's save() method handles username/code generation
        serializer.save(prompt=prompt)
        # Similar to prompts, add modification_code back to the response data
        instance = serializer.instance
        response_data = CommentSerializer(instance).data
        response_data['modification_code'] = instance.modification_code
        # Again, this needs to be handled by overriding create() or adjusting the response later.
        # Relying on PRD flow for now.


# Apply decorator to dispatch for CBVs
@method_decorator(ratelimit(key='ip', rate='50/d', method=['PUT', 'PATCH', 'DELETE'], block=True), name='dispatch')
class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/comments/:comment_id/ : Retrieve a single comment (Not in PRD, but included by default)
    PUT    /api/comments/:comment_id/ : Update a comment (requires modification_code)
    PATCH  /api/comments/:comment_id/ : Partially update a comment (requires modification_code)
    DELETE /api/comments/:comment_id/ : Delete a comment (requires modification_code)
    """
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    lookup_field = 'comment_id' # Use UUID field for lookup

    def check_modification_code(self, request, instance):
        """Helper to check modification code from request body."""
        code = request.data.get('modification_code')
        if not code:
            raise PermissionDenied("Modification code is required.")
        # Ensure case-insensitive comparison if codes are stored consistently
        if code.lower() != instance.modification_code.lower():
            raise PermissionDenied("Invalid modification code.")
        return True

    # Remove decorators from put, patch, delete
    def put(self, request, *args, **kwargs):
        # Remove the manual check
        instance = self.get_object()
        self.check_modification_code(request, instance)
        # Prevent username update
        if 'username' in request.data:
             request.data.pop('username')
        return super().update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        # Remove the manual check
        instance = self.get_object()
        self.check_modification_code(request, instance)
        # Prevent username update
        if 'username' in request.data:
             request.data.pop('username')
        return super().partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        # Remove the manual check
        instance = self.get_object()
        try:
            self.check_modification_code(request, instance)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Tag View ---

class TagListView(views.APIView):
    """
    GET /api/tags/ : Retrieve a unique list of all tags used across prompts.
    """
    # No rate limiting needed for GET tags (as per PRD)

    def get(self, request, *args, **kwargs):
        """
        Return a sorted list of unique tags.
        """
        # Retrieve all non-null, non-empty tag arrays from prompts
        all_tags_lists = Prompt.objects.exclude(tags__isnull=True).exclude(tags__len=0).values_list('tags', flat=True)

        # Flatten the list of lists and get unique tags
        unique_tags = set()
        for tag_list in all_tags_lists:
            if tag_list: # Ensure the list itself isn't None/empty after exclusion
                unique_tags.update(tag for tag in tag_list if tag) # Add non-empty tags

        # Sort the unique tags alphabetically
        sorted_tags = sorted(list(unique_tags))

        return Response(sorted_tags, status=status.HTTP_200_OK)


# --- Other Views ---

class RandomPromptView(views.APIView):
    """
    GET /api/prompts/random : Retrieve a single random prompt.
    """
    # No rate limiting specified

    def get(self, request, *args, **kwargs):
        """
        Return a single random prompt using the full PromptSerializer.
        Note: order_by('?') can be inefficient on large tables.
        """
        random_prompt = Prompt.objects.order_by('?').first()
        if not random_prompt:
            return Response({"detail": "No prompts available."}, status=status.HTTP_404_NOT_FOUND)

        # We need to manually handle the comment pagination like in PromptDetailView.retrieve
        comments_queryset = random_prompt.comments.all()[:10]
        comment_serializer = CommentSerializer(comments_queryset, many=True)

        prompt_serializer = PromptSerializer(random_prompt)
        prompt_data = prompt_serializer.data

        prompt_data['comments'] = comment_serializer.data
        total_comments = random_prompt.comments.count()
        prompt_data['comment_pagination'] = {
            'total_count': total_comments,
            'page_size': 10,
            'has_more': total_comments > 10
        }

        return Response(prompt_data, status=status.HTTP_200_OK)


class BatchPromptView(views.APIView):
    """
    POST /api/prompts/batch : Retrieve multiple prompts by their IDs.
    Expects JSON body: {"ids": ["uuid1", "uuid2", ...]}
    """
    # No rate limiting specified

    def post(self, request, *args, **kwargs):
        """
        Return a list of prompts matching the provided IDs using PromptListSerializer.
        """
        serializer = PromptBatchIdSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        prompt_ids = serializer.validated_data['ids']

        # Fetch prompts matching the IDs. Use __in lookup.
        # Preserve the order of the input IDs if possible/needed, though __in doesn't guarantee it.
        # If order matters, fetch individually or re-order after fetching.
        # For simplicity, we won't guarantee order here.
        prompts = Prompt.objects.filter(prompt_id__in=prompt_ids)

        # Use PromptListSerializer (no comments) for the response
        response_serializer = PromptListSerializer(prompts, many=True)

        return Response(response_serializer.data, status=status.HTTP_200_OK)


# --- Root API View ---

class ApiRootView(views.APIView):
    """
    GET /api/ : Basic status check for the API.
    """
    # No rate limiting needed for root check
    def get(self, request, *args, **kwargs):
        db_status = "ok"
        db_error = None
        try:
            # Optional: Perform a simple database check
            connection.ensure_connection()
            # Or try a simple query like Prompt.objects.count()
        except OperationalError as e:
            db_status = "error"
            db_error = str(e)
            # Log the error for debugging on Vercel
            print(f"Database connection error: {e}") # Vercel logs this

        status_data = {
            "status": "ok",
            "message": "PromptBase API is running.",
            "database_connection": db_status
        }
        if db_error:
            status_data["database_error"] = db_error

        response_status = status.HTTP_200_OK if db_status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE

        return Response(status_data, status=response_status)

# End of views.py
