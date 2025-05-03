from django.shortcuts import render
from rest_framework import generics, status, views
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.db import connection
from django.db.utils import OperationalError
from django.utils.decorators import method_decorator
from rest_framework.pagination import PageNumberPagination
from django.http import JsonResponse
from django.core.cache import cache # <<< ADD THIS IMPORT
import time # <<< ADD THIS IMPORT

# Import models and serializers
from .models import Prompt, Comment
from .serializers import (
    PromptSerializer,
    PromptListSerializer,
    CommentSerializer,
    PromptBatchIdSerializer
)

# Import rate limiting decorators
from django_ratelimit.decorators import ratelimit

# --- ratelimited_error function ---
def ratelimited_error(request, exception):
    """
    Custom view to return a JSON 429 response when rate limited.
    """
    # You can customize the response format if needed
    return JsonResponse(
        {'detail': 'Request was throttled.'},
        status=status.HTTP_429_TOO_MANY_REQUESTS
    )
# --- END ADDITION ---

# --- ADD THIS TEST VIEW ---
class CacheTestView(views.APIView):
    def get(self, request, *args, **kwargs):
        cache_key = "my_test_key"
        current_time = time.time()
        try:
            # Try to set a value
            cache.set(cache_key, f"Cache set at {current_time}", timeout=60)
            # Try to get the value
            retrieved_value = cache.get(cache_key)
            # Try atomic increment (required by ratelimit)
            incr_key = "my_incr_key"
            try:
                count = cache.incr(incr_key)
                incr_status = f"Increment successful, count: {count}"
            except ValueError:
                # If key doesn't exist, incr might raise ValueError. Set it first.
                cache.set(incr_key, 0, timeout=60)
                count = cache.incr(incr_key)
                incr_status = f"Increment successful after setting, count: {count}"


            return Response({
                "status": "Cache test successful",
                "set_value": f"Cache set at {current_time}",
                "retrieved_value": retrieved_value,
                "increment_status": incr_status,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            # Catch any exception during cache operations
            return Response({
                "status": "Cache test failed",
                "error": str(e),
                "error_type": type(e).__name__
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# --- END TEST VIEW ---


# --- Custom Pagination ---
class StandardResultsSetPagination(PageNumberPagination): # <<< Definition was already here
    page_size = 10
    page_size_query_param = 'limit'
    max_page_size = 100

# --- Prompt Views ---
@method_decorator(ratelimit(key='ip', rate='50/d', method='POST', block=True), name='dispatch')
class PromptListCreateView(generics.ListCreateAPIView):
    queryset = Prompt.objects.all().order_by('-updated_at')
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PromptSerializer
        return PromptListSerializer

    def create(self, request, *args, **kwargs):
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
        queryset = super().get_queryset()
        search_query = self.request.query_params.get('search', None)
        tags_query = self.request.query_params.get('tags', None)
        sort_query = self.request.query_params.get('sort', None)

        # Search
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) | Q(content__icontains=search_query)
            )

        # Filter by Tags (using raw SQL fragment via .extra())
        if tags_query:
            tags_list = [tag.strip() for tag in tags_query.split(',') if tag.strip()]
            if tags_list:
                # Use .extra() to add a WHERE clause with the && operator
                # Django will handle parameterization safely (%s)
                queryset = queryset.extra(where=['tags && %s'], params=[tags_list])

        # Sort
        if sort_query:
            sort_map = {
                'title_asc': 'title',
                'title_desc': '-title',
                'updated_at_asc': 'updated_at',
                'updated_at_desc': '-updated_at',
            }
            sort_field = sort_map.get(sort_query.lower())
            if sort_field:
                 queryset = queryset.order_by(sort_field)

        return queryset

# Apply decorator for PromptDetailView update/delete
@method_decorator(ratelimit(key='ip', rate='50/d', method=['PUT', 'PATCH', 'DELETE'], block=True), name='dispatch')
class PromptDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer
    lookup_field = 'prompt_id'

    def check_modification_code(self, request, instance):
        """Checks if the provided modification code matches the instance's code."""
        code = request.data.get('modification_code')
        if not code:
            raise ValidationError({"modification_code": "This field is required."})
        # Compare the provided code with the instance's field value
        if instance.modification_code != code: # <<< CORRECTED LINE
            # PREVIOUSLY: if not instance.check_modification_code(code):
            raise PermissionDenied("Invalid modification code.")

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        try:
            self.check_modification_code(request, instance)
        except (ValidationError, PermissionDenied) as e:
            if isinstance(e, PermissionDenied):
                 return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
            raise e

        if 'username' in request.data:
            mutable_data = request.data.copy()
            mutable_data.pop('username', None)
            request._full_data = mutable_data

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        comments_queryset = instance.comments.all()[:10]
        comment_serializer = CommentSerializer(comments_queryset, many=True)
        response_data = serializer.data
        response_data['comments'] = comment_serializer.data
        total_comments = instance.comments.count()
        response_data['comment_pagination'] = {
            'total_count': total_comments,
            'page_size': 10,
            'has_more': total_comments > 10
        }
        return Response(response_data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.check_modification_code(request, instance)
        except (ValidationError, PermissionDenied) as e:
            if isinstance(e, PermissionDenied):
                 return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
            return Response({"detail": "Modification code is required."}, status=status.HTTP_403_FORBIDDEN)

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        comments_queryset = instance.comments.all()[:10]
        comment_serializer = CommentSerializer(comments_queryset, many=True)
        prompt_serializer = self.get_serializer(instance)
        prompt_data = prompt_serializer.data
        prompt_data['comments'] = comment_serializer.data
        total_comments = instance.comments.count()
        prompt_data['comment_pagination'] = {
            'total_count': total_comments,
            'page_size': 10,
            'has_more': total_comments > 10
        }
        return Response(prompt_data)


# --- Comment Views ---
@method_decorator(ratelimit(key='ip', rate='50/d', method='POST', block=True), name='dispatch')
class CommentListCreateView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        prompt_id = self.kwargs.get('prompt_id')
        get_object_or_404(Prompt, prompt_id=prompt_id)
        return Comment.objects.filter(prompt_id=prompt_id)

    def create(self, request, *args, **kwargs):
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

@method_decorator(ratelimit(key='ip', rate='50/d', method=['PUT', 'PATCH', 'DELETE'], block=True), name='dispatch')
class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    lookup_field = 'comment_id'

    def check_modification_code(self, request, instance):
        """Checks if the provided modification code matches the instance's code."""
        code = request.data.get('modification_code')
        if not code:
            raise ValidationError({"modification_code": "This field is required."})
        # Compare the provided code with the instance's field value
        if instance.modification_code != code: # <<< CORRECTED LINE
            # PREVIOUSLY: if not instance.check_modification_code(code):
            raise PermissionDenied("Invalid modification code.")

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        try:
            self.check_modification_code(request, instance)
        except (ValidationError, PermissionDenied) as e:
            if isinstance(e, PermissionDenied):
                 return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
            raise e

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
            self.check_modification_code(request, instance)
        except (ValidationError, PermissionDenied) as e:
            if isinstance(e, PermissionDenied):
                 return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
            return Response({"detail": "Modification code is required."}, status=status.HTTP_403_FORBIDDEN)

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Tag View ---
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
    def get(self, request, *args, **kwargs):
        random_prompt = Prompt.objects.order_by('?').first()
        if not random_prompt:
            return Response({"detail": "No prompts available."}, status=status.HTTP_404_NOT_FOUND)

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
    def post(self, request, *args, **kwargs):
        serializer = PromptBatchIdSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        prompt_ids = serializer.validated_data['ids']
        prompts = Prompt.objects.filter(prompt_id__in=prompt_ids)
        response_serializer = PromptListSerializer(prompts, many=True)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


# --- Root API View ---
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
