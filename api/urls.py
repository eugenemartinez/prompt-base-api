from django.urls import path
from . import views # Import views from the current app

urlpatterns = [
    # Root API view (add this first)
    path('', views.ApiRootView.as_view(), name='api-root'),

    # Prompt URLs
    path('prompts/', views.PromptListCreateView.as_view(), name='prompt-list-create'),
    # Specific paths like 'random' and 'batch' should come BEFORE the general <uuid:prompt_id> path
    path('prompts/random/', views.RandomPromptView.as_view(), name='prompt-random'),
    path('prompts/batch/', views.BatchPromptView.as_view(), name='prompt-batch'),
    path('prompts/<uuid:prompt_id>/', views.PromptDetailView.as_view(), name='prompt-detail'),

    # Comment URLs
    # List comments for a prompt or Create a comment for a prompt
    path('prompts/<uuid:prompt_id>/comments/', views.CommentListCreateView.as_view(), name='comment-list-create'),
    # Update/Delete a specific comment
    path('comments/<uuid:comment_id>/', views.CommentDetailView.as_view(), name='comment-detail'),

    # Tag URLs
    path('tags/', views.TagListView.as_view(), name='tag-list'),

    # Note: It's important that more specific paths like /prompts/random/
    # come *before* more general paths like /prompts/<uuid:prompt_id>/
    # so that Django matches 'random' correctly instead of treating it as a UUID.
]