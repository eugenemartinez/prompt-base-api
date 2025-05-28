from django.shortcuts import render
from rest_framework import generics, status, views
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count # <--- Import Count
from django.db.models.functions import Lower
from django.db import connection
from django.db.utils import OperationalError
from django.utils.decorators import method_decorator
from rest_framework.pagination import PageNumberPagination
from django.http import JsonResponse
from django.core.cache import cache
import time
from rest_framework.reverse import reverse
import uuid # Import the uuid module
import os # <--- Import os

# Import models and serializers
from .models import Prompt, Comment # Ensure these are imported
from .serializers import ( # Ensure these are imported
    PromptSerializer,
    PromptListSerializer,
    CommentSerializer,
    PromptBatchIdSerializer
)

# Import rate limiting decorators
from django_ratelimit.decorators import ratelimit

# --- Define a single global rate limit from environment variable ---
# Defaulting to a high rate for easier testing if not set.
# Adjust the default '1000/s' as needed for your typical non-testing scenario,
# or rely on setting it in .env for production/staging.
GLOBAL_API_RATE = os.environ.get('GLOBAL_API_RATE_LIMIT', '1000/s')
print(f"--- GLOBAL_API_RATE set to: {GLOBAL_API_RATE} ---") # For verification

# --- ratelimited_error function ---
def ratelimited_error(request, exception):
    """
    Custom view to return a JSON 429 response when rate limited.
    """
    # You can customize the response format if needed
    return JsonResponse(
        # --- UPDATE THE DETAIL MESSAGE ---
        {'detail': 'You have made too many requests in a short period. Please try again later.'},
        # --- END UPDATE ---
        status=status.HTTP_429_TOO_MANY_REQUESTS
    )
# --- END ADDITION ---

# --- Cache Test View (Corrected) ---
class CacheTestView(views.APIView):

    def get(self, request, *args, **kwargs):
        """Handles GET requests to retrieve a value from the cache."""
        key = request.query_params.get('key')
        if not key:
            return Response({'error': 'Missing key query parameter'}, status=status.HTTP_400_BAD_REQUEST)

        value = cache.get(key)
        if value is not None:
            return Response({'status': 'Cache hit', 'key': key, 'value': value}, status=status.HTTP_200_OK)
        else:
            return Response({'status': 'Cache miss', 'key': key}, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        """Handles POST requests to set a value in the cache."""
        key = request.data.get('key')
        value = request.data.get('value')

        if not key or value is None: # Check if value is None explicitly
            return Response({'error': 'Missing key or value in request body'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Set with a default timeout (e.g., 5 minutes)
            cache.set(key, value, timeout=300)
            return Response({'status': 'Cache set', 'key': key, 'value': value}, status=status.HTTP_201_CREATED)
        except Exception as e:
            # Catch potential cache backend errors
            return Response({
                "status": "Cache set failed",
                "error": str(e),
                "error_type": type(e).__name__
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, *args, **kwargs):
        """Handles DELETE requests to remove a key from the cache."""
        key = request.query_params.get('key')
        if not key:
            return Response({'error': 'Missing key query parameter'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if key exists before deleting for a more informative response
        exists = cache.has_key(key) # Use has_key or check if get(key) is not None

        if exists:
            try:
                cache.delete(key)
                return Response({'status': 'Cache deleted', 'key': key}, status=status.HTTP_200_OK)
            except Exception as e:
                 # Catch potential cache backend errors
                return Response({
                    "status": "Cache delete failed",
                    "error": str(e),
                    "error_type": type(e).__name__
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # Key doesn't exist, return success but indicate it wasn't found
            return Response({'status': 'Cache key not found or already deleted', 'key': key}, status=status.HTTP_200_OK)

# --- END Cache Test View ---

# --- Custom Pagination ---
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'limit'
    max_page_size = 100

# --- Prompt Views ---
@method_decorator(ratelimit(key='ip', rate=GLOBAL_API_RATE, method='POST', block=True), name='dispatch')
class PromptListCreateView(generics.ListCreateAPIView):
    queryset = Prompt.objects.all()
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PromptSerializer
        return PromptListSerializer

    def create(self, request, *args, **kwargs):
        # --- ADD HARD LIMIT CHECK FOR PROMPTS ---
        PROMPT_ROW_LIMIT = 500
        if Prompt.objects.count() >= PROMPT_ROW_LIMIT:
            return Response(
                {"detail": f"Cannot create new prompt. The system has reached its maximum capacity of {PROMPT_ROW_LIMIT} prompts."},
                status=status.HTTP_403_FORBIDDEN # Or status.HTTP_503_SERVICE_UNAVAILABLE
            )
        # --- END HARD LIMIT CHECK ---

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        instance = serializer.instance
        response_data = serializer.data
        response_data['modification_code'] = instance.modification_code
        headers = self.get_success_headers(response_data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save()

    def get_queryset(self):
        """Optionally filter and sort the queryset."""
        # Start with the base queryset and annotate
        # NOTE: Using .all() here again, consistent with original structure,
        # but applying annotation. If class queryset is used, adjust accordingly.
        queryset = Prompt.objects.annotate(
            comment_count=Count('comments') # <--- Add annotation here
        )
        search_query = self.request.query_params.get('search', None)
        tags_query = self.request.query_params.get('tags', None)
        sort_query = self.request.query_params.get('sort', 'updated_at_desc')

        # Search
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) | Q(content__icontains=search_query)
            )

        # Filter by Tags
        if tags_query:
            tags_list = [tag.strip() for tag in tags_query.split(',') if tag.strip()]
            if tags_list:
                # --- CORRECTED FILTERING ---
                # Use the ORM's __overlap lookup instead of .extra()
                queryset = queryset.filter(tags__overlap=tags_list)
                # --- END CORRECTION ---

        # Sort (Apply default or query param)
        sort_map = {
            'title_asc': Lower('title').asc(),
            'title_desc': Lower('title').desc(),
            'updated_at_asc': 'updated_at',
            'updated_at_desc': '-updated_at',
        }
        ordering = sort_map.get(sort_query.lower())

        if ordering:
             queryset = queryset.order_by(ordering)
        # else:
        #     queryset = queryset.order_by('-updated_at')

        return queryset

# Apply decorator for PromptDetailView update/delete
@method_decorator(ratelimit(key='ip', rate=GLOBAL_API_RATE, method=['PUT', 'PATCH', 'DELETE'], block=True), name='dispatch')
class PromptDetailView(generics.RetrieveUpdateDestroyAPIView):
    # ... (Keep ALL existing PromptDetailView code exactly the same) ...
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer
    lookup_field = 'prompt_id'

    def check_modification_code(self, request, instance):
        """Checks if the provided modification code matches the instance's code."""
        code = request.data.get('modification_code')
        if not code:
            # --- CORRECTED LINE ---
            # Raise PermissionDenied for missing code (results in 403)
            raise PermissionDenied("Modification code is required.")
            # --- END CORRECTION ---
        if instance.modification_code != code:
            raise PermissionDenied("Invalid modification code") # Keep this for wrong code

    def _get_comment_pagination_url(self, page_number, request):
        if not page_number:
            return None
        try:
            base_url = reverse('api:comment-list-create', kwargs={'prompt_id': self.kwargs['prompt_id']}, request=request)
            return f"{base_url}?page={page_number}"
        except Exception as e:
            print(f"Error reversing comment URL: {e}")
            return None

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        try:
            # This will now raise PermissionDenied for missing OR wrong code
            self.check_modification_code(request, instance)
        except PermissionDenied as e: # Catch only PermissionDenied
             return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        if 'username' in request.data:
            mutable_data = request.data.copy()
            mutable_data.pop('username', None)
            request._full_data = mutable_data
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
        comments_queryset = instance.comments.all()
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(comments_queryset, request, view=self)
        if page is not None:
            comment_serializer = CommentSerializer(page, many=True)
            comments_data = {
                'count': paginator.page.paginator.count,
                'next': self._get_comment_pagination_url(paginator.page.next_page_number() if paginator.page.has_next() else None, request),
                'previous': self._get_comment_pagination_url(paginator.page.previous_page_number() if paginator.page.has_previous() else None, request),
                'results': comment_serializer.data
            }
        else:
             comment_serializer = CommentSerializer(comments_queryset, many=True)
             comments_data = {
                'count': comments_queryset.count(),
                'next': None,
                'previous': None,
                'results': comment_serializer.data
             }
        response_data = serializer.data
        response_data['comments'] = comments_data
        response_data.pop('comment_pagination', None)
        return Response(response_data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            # This will now raise PermissionDenied for missing OR wrong code
            self.check_modification_code(request, instance)
        except PermissionDenied as e: # Catch only PermissionDenied
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        prompt_serializer = self.get_serializer(instance)
        prompt_data = prompt_serializer.data
        comments_queryset = instance.comments.all()
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(comments_queryset, request, view=self)
        if page is not None:
            comment_serializer = CommentSerializer(page, many=True)
            next_page_num_for_helper = paginator.page.next_page_number() if paginator.page.has_next() else None
            comments_data = {
                'count': paginator.page.paginator.count,
                'next': self._get_comment_pagination_url(next_page_num_for_helper, request),
                'previous': self._get_comment_pagination_url(paginator.page.previous_page_number() if paginator.page.has_previous() else None, request),
                'results': comment_serializer.data
            }
        else:
             comment_serializer = CommentSerializer(comments_queryset, many=True)
             comments_data = {
                'count': comments_queryset.count(),
                'next': None,
                'previous': None,
                'results': comment_serializer.data
             }
        prompt_data['comments'] = comments_data
        prompt_data.pop('comment_pagination', None)
        return Response(prompt_data)


# --- Comment Views ---
@method_decorator(ratelimit(key='ip', rate=GLOBAL_API_RATE, method='POST', block=True), name='dispatch')
class CommentListCreateView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        prompt_id = self.kwargs.get('prompt_id')
        get_object_or_404(Prompt, prompt_id=prompt_id)
        return Comment.objects.filter(prompt_id=prompt_id)

    def create(self, request, *args, **kwargs):
        # --- ADD HARD LIMIT CHECK FOR COMMENTS ---
        COMMENT_ROW_LIMIT = 500
        if Comment.objects.count() >= COMMENT_ROW_LIMIT:
            return Response(
                {"detail": f"Cannot create new comment. The system has reached its maximum capacity of {COMMENT_ROW_LIMIT} comments."},
                status=status.HTTP_403_FORBIDDEN # Or status.HTTP_503_SERVICE_UNAVAILABLE
            )
        # --- END HARD LIMIT CHECK ---

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        instance = serializer.instance
        response_data = serializer.data
        response_data['modification_code'] = instance.modification_code
        headers = self.get_success_headers(response_data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        prompt_id = self.kwargs.get('prompt_id')
        prompt = get_object_or_404(Prompt, prompt_id=prompt_id)
        serializer.save(prompt=prompt)

@method_decorator(ratelimit(key='ip', rate=GLOBAL_API_RATE, method=['PUT', 'PATCH', 'DELETE'], block=True), name='dispatch')
class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    lookup_field = 'comment_id'

    def check_modification_code(self, request, instance):
        """Checks if the provided modification code matches the instance's code."""
        code = request.data.get('modification_code')
        if not code:
            # --- CORRECTED LINE ---
            # Raise PermissionDenied for missing code (results in 403)
            raise PermissionDenied("Modification code is required.")
            # --- END CORRECTION ---
        if instance.modification_code != code:
            raise PermissionDenied("Invalid modification code.") # Keep this for wrong code

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        try:
            # This will now raise PermissionDenied for missing OR wrong code
            self.check_modification_code(request, instance)
        except PermissionDenied as e: # Catch only PermissionDenied
             return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        if 'username' in request.data:
            mutable_data = request.data.copy()
            mutable_data.pop('username', None)
            request._full_data = mutable_data
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
        response_data = serializer.data
        return Response(response_data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            # This will now raise PermissionDenied for missing OR wrong code
            self.check_modification_code(request, instance)
        except PermissionDenied as e: # Catch only PermissionDenied
             return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Tag View ---
# ... (Keep ALL existing TagListView code exactly the same) ...
class TagListView(views.APIView):
    def get(self, request, *args, **kwargs):
        all_tags_lists = Prompt.objects.exclude(tags__isnull=True).exclude(tags__len=0).values_list('tags', flat=True)
        unique_tags = set()
        for tag_list in all_tags_lists:
            if tag_list:
                unique_tags.update(tag for tag in tag_list if tag)
        sorted_tags = sorted(list(unique_tags))
        return Response(sorted_tags, status=status.HTTP_200_OK)


# --- Other Views ---
class RandomPromptView(views.APIView):
    # Keep original logic exactly as provided
    def get(self, request, *args, **kwargs):
        random_prompt = Prompt.objects.order_by('?').first()
        if not random_prompt:
            return Response({"detail": "No prompts available."}, status=status.HTTP_404_NOT_FOUND)

        comments_queryset = random_prompt.comments.all()[:10]
        comment_serializer = CommentSerializer(comments_queryset, many=True)
        prompt_serializer = PromptSerializer(random_prompt) # Use original serializer
        prompt_data = prompt_serializer.data
        prompt_data['comments'] = comment_serializer.data # Use original comment handling
        total_comments = random_prompt.comments.count()
        # Keep original pagination structure for this view
        prompt_data['comment_pagination'] = {
            'total_count': total_comments,
            'page_size': 10,
            'has_more': total_comments > 10
        }
        return Response(prompt_data, status=status.HTTP_200_OK)


class BatchPromptView(views.APIView):
    def post(self, request, *args, **kwargs):
        serializer = PromptBatchIdSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Get the list of strings from the validated data
        potential_ids = serializer.validated_data.get('ids', [])

        # --- Filter for valid UUIDs ---
        valid_prompt_ids = []
        for item in potential_ids:
            try:
                # Attempt to convert string to UUID
                valid_uuid = uuid.UUID(item)
                valid_prompt_ids.append(valid_uuid)
            except (ValueError, TypeError):
                # Ignore items that are not valid UUID strings
                continue
        # --- End Filter ---

        # If no valid UUIDs remain after filtering, return empty list
        if not valid_prompt_ids:
            return Response([], status=status.HTTP_200_OK)

        # Filter and annotate using only the valid UUIDs
        prompts = Prompt.objects.filter(prompt_id__in=valid_prompt_ids).annotate(
            comment_count=Count('comments')
        )
        response_serializer = PromptListSerializer(prompts, many=True)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


# --- Root API View ---
# ... (Keep ALL existing ApiRootView code exactly the same) ...
class ApiRootView(views.APIView):
    def get(self, request, *args, **kwargs):
        db_status = "ok"
        db_error = None
        try:
            connection.ensure_connection()
        except OperationalError as e:
            db_status = "error"
            db_error = str(e)
            print(f"Database connection error: {e}")

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
