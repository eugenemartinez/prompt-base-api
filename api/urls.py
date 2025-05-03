from django.urls import path
from . import views

# Define app_name if you plan to use namespacing (optional but good practice)
app_name = 'api'

urlpatterns = [
    # --- Root View ---
    path('', views.ApiRootView.as_view(), name='api-root'),

    # --- Prompt Views ---
    path('prompts/', views.PromptListCreateView.as_view(), name='prompt-list-create'),
    path('prompts/random/', views.RandomPromptView.as_view(), name='prompt-random'),
    path('prompts/batch/', views.BatchPromptView.as_view(), name='prompt-batch'),
    path('prompts/<uuid:prompt_id>/', views.PromptDetailView.as_view(), name='prompt-detail'),

    # --- Comment Views ---
    # List/Create comments for a specific prompt
    path('prompts/<uuid:prompt_id>/comments/', views.CommentListCreateView.as_view(), name='comment-list-create'),
    # Retrieve/Update/Delete a specific comment (using its own ID)
    path('comments/<uuid:comment_id>/', views.CommentDetailView.as_view(), name='comment-detail'),

    # --- Tag View ---
    path('tags/', views.TagListView.as_view(), name='tag-list'),

    # --- Additional Views ---
    path('cache-test/', views.CacheTestView.as_view(), name='cache-test'),
]