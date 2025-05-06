# PromptBase Backend API

This is the backend API for PromptBase, built with Django and Django REST Framework.

## Prerequisites

*   **Python:** Version 3.9 (Running on Vercel)
*   **Database:** PostgreSQL (or specify if different) - Ensure the database server is running.
*   **Cache:** Redis (or specify if different, e.g., Memcached) - Required for rate limiting and potentially other caching.

## Installation

1.  **Clone the repository (if needed) and navigate to the `prompt-base-api` directory:**
    ```bash
    # Example:
    # git clone https://github.com/eugenemartinez/prompt-base-api
    # cd prompt-base-api
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  **Environment Variables:**
    Create a `.env` file in the `prompt-base-api` directory. You can often copy `.env.example` if it exists. Set necessary variables, including:
    *   `DJANGO_SECRET_KEY`: Your Django secret key.
    *   `DATABASE_URL`: Connection string for your PostgreSQL database (e.g., `postgres://user:password@host:port/dbname`).
    *   `REDIS_URL`: Connection string for your Redis cache (e.g., `redis://localhost:6379/1`).
    *   `DJANGO_ALLOWED_HOSTS`: Comma-separated list of allowed hostnames (e.g., `localhost,127.0.0.1,yourdomain.com`).
    *   `CORS_ALLOWED_ORIGINS`: Comma-separated list of frontend origins allowed to make requests (e.g., `http://localhost:5173,https://yourfrontenddomain.com`).
    *   `DJANGO_DEBUG`: Set to `True` for development (shows detailed errors) or `False` for production. **Important:** Never run with `DEBUG=True` in production!

2.  **Database Migrations:**
    Apply the database schema changes:
    ```bash
    python manage.py migrate
    ```

## Running Locally (Development)

To start the Django development server:

```bash
python manage.py runserver
```

The API will typically be available at `http://localhost:8000/api/`. Ensure `DJANGO_DEBUG` is set to `True` in your `.env` file for local development.

## API Routes

The following routes are available under the `/api/` base path:

*   **Root:**
    *   `GET /api/`: API Root and status check.
*   **Prompts:**
    *   `GET /api/prompts/`: List prompts (paginated, searchable, sortable, filter by tags).
    *   `POST /api/prompts/`: Create a new prompt.
    *   `GET /api/prompts/random/`: Get a single random prompt with comments.
    *   `POST /api/prompts/batch/`: Get details for multiple prompts by ID.
    *   `GET /api/prompts/<uuid:prompt_id>/`: Retrieve details for a specific prompt (includes paginated comments).
    *   `PUT /api/prompts/<uuid:prompt_id>/`: Update a specific prompt (requires `modification_code`).
    *   `PATCH /api/prompts/<uuid:prompt_id>/`: Partially update a specific prompt (requires `modification_code`).
    *   `DELETE /api/prompts/<uuid:prompt_id>/`: Delete a specific prompt (requires `modification_code`).
*   **Comments:**
    *   `GET /api/prompts/<uuid:prompt_id>/comments/`: List comments for a specific prompt (paginated).
    *   `POST /api/prompts/<uuid:prompt_id>/comments/`: Create a new comment for a specific prompt.
    *   `GET /api/comments/<uuid:comment_id>/`: Retrieve details for a specific comment.
    *   `PUT /api/comments/<uuid:comment_id>/`: Update a specific comment (requires `modification_code`).
    *   `PATCH /api/comments/<uuid:comment_id>/`: Partially update a specific comment (requires `modification_code`).
    *   `DELETE /api/comments/<uuid:comment_id>/`: Delete a specific comment (requires `modification_code`).
*   **Tags:**
    *   `GET /api/tags/`: Get a list of all unique tags used in prompts.
*   **Utilities:**
    *   `GET /api/cache-test/`: Test cache connectivity (for debugging).

## Running in Production

For production, use a production-ready WSGI server like Gunicorn or uWSGI behind a reverse proxy like Nginx.

```bash
# Example using Gunicorn (replace 'promptbase' with your actual Django project name):
# gunicorn promptbase.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

Ensure environment variables are set correctly in your production environment, **especially `DJANGO_DEBUG=False`**.