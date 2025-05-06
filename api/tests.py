import warnings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.test import override_settings, SimpleTestCase # Import SimpleTestCase for setUpModule context
from .models import Prompt, Comment
from django.core.cache import cache # Import cache for setup/teardown

# --- Suppress WhiteNoise warning ---
warnings.filterwarnings(
    'ignore',
    category=UserWarning,
    message='No directory at.*staticfiles.*'
)

# --- Module level setup to silence ratelimit check early ---
def setUpModule():
    """Silence system checks before tests run."""
    # Use override_settings as a context manager here
    # Note: This requires entering the context, but it might not persist
    # outside this function easily. A better way might be needed if this fails.
    # Let's try the decorator on a dummy class first.

    # Alternative: Decorate a dummy class to apply settings early? Less clean.
    # Let's stick to the filterwarnings for now if it worked for WhiteNoise.
    # It's possible the ratelimit warning isn't using the standard warnings system.

    # --- Re-add the ratelimit filterwarning, ensure regex is correct ---
    warnings.filterwarnings(
        'ignore',
        message=r'.*cache backend django\.core\.cache\.backends\.locmem\.LocMemCache is not officially supported.*'
    )
    # --- End Re-add ---


# --- Prompt API Tests ---
# Remove the override_settings decorator from the class if filterwarnings is used
# @override_settings(SILENCED_SYSTEM_CHECKS=["django_ratelimit.W001"]) # <-- Remove or comment out
class PromptAPITests(APITestCase):
    """
    Tests for the /api/prompts/ endpoint.
    """

    # --- Helper Method ---
    def _create_prompt(self, title="Sample Title", content="Sample content.", tags=None):
        """Helper method to create a prompt directly in the DB for testing GET requests."""
        if tags is None:
            tags = ["sample", "test"]
        return Prompt.objects.create(title=title, content=content, tags=tags)
    # --- End Helper ---


    def test_create_prompt_success(self):
        """
        Ensure we can create a new prompt object.
        """
        url = reverse('api:prompt-list-create') # <-- Add the 'api:' namespace prefix
        data = {
            'title': 'Test Prompt Title',
            'content': 'This is the test prompt content.',
            'tags': ['test', 'api', 'python']
        }
        response = self.client.post(url, data, format='json')

        # Assertions
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Prompt.objects.count(), 1) # Check if one prompt exists in the DB
        prompt = Prompt.objects.get() # Get the created prompt
        self.assertEqual(prompt.title, 'Test Prompt Title')
        self.assertEqual(prompt.content, 'This is the test prompt content.')
        self.assertListEqual(sorted(prompt.tags), sorted(['test', 'api', 'python'])) # Check tags (order might vary)
        self.assertIsNotNone(prompt.username) # Check if username was generated
        self.assertIsNotNone(prompt.modification_code) # Check if mod code was generated

        # Check response data structure
        self.assertIn('prompt_id', response.data)
        self.assertEqual(response.data['title'], data['title'])
        self.assertEqual(response.data['content'], data['content'])
        self.assertListEqual(sorted(response.data['tags']), sorted(data['tags']))
        self.assertIn('username', response.data)
        self.assertIn('modification_code', response.data) # Mod code SHOULD be in the POST response
        self.assertIsNotNone(response.data['modification_code']) # Optionally check it's not null/empty

    def test_create_prompt_missing_fields(self):
        """
        Ensure API returns 400 Bad Request if required fields like title/content are missing.
        Tags field is optional due to model definition (blank=True, default=list).
        """
        url = reverse('api:prompt-list-create')

        # Test missing title (Should fail)
        data_missing_title = {
            # 'title': 'Missing',
            'content': 'This prompt has no title.',
            'tags': ['validation']
        }
        response_missing_title = self.client.post(url, data_missing_title, format='json')
        self.assertEqual(response_missing_title.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response_missing_title.data)

        # Test missing content (Should fail)
        data_missing_content = {
            'title': 'Prompt without Content',
            # 'content': 'Missing',
            'tags': ['validation']
        }
        response_missing_content = self.client.post(url, data_missing_content, format='json')
        self.assertEqual(response_missing_content.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', response_missing_content.data)

        # Ensure no prompt was created during the *failed* attempts (missing title/content)
        # If you removed the 'missing tags' block entirely:
        self.assertEqual(Prompt.objects.count(), 0)
        # If you kept and modified the 'missing tags' block to assert success and cleanup:
        # self.assertEqual(Prompt.objects.count(), 0) # This would still be 0 after cleanup

    def test_create_prompt_invalid_tags(self):
        """
        Ensure API returns 400 Bad Request for various invalid tag scenarios.
        """
        url = reverse('api:prompt-list-create')
        base_data = {
            'title': 'Tag Validation Test',
            'content': 'Testing different invalid tag inputs.',
        }

        invalid_tag_cases = [
            (['tag with space'], "Spaces not allowed"),
            (['tag<script>'], "Invalid characters"),
            (['tag!@#'], "Invalid characters"),
            ([''], "Empty tag string"),
            (['   '], "Whitespace-only tag"),
            (['a'*51], "Tag too long"), # Assuming max_length=50
            (['valid', 'valid'], "Duplicate tags"),
            ([' valid ', 'valid'], "Duplicate tags after cleaning"),
            (['tag1', ' TAG1 '], "Duplicate tags case-insensitive after cleaning"), # Serializer validation is case-sensitive, model might differ
        ]

        for tags, description in invalid_tag_cases:
            with self.subTest(description=description, tags=tags):
                data = {**base_data, 'tags': tags}
                response = self.client.post(url, data, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, f"Failed for: {description}")
                self.assertIn('tags', response.data, f"Failed for: {description}")

        # Ensure no prompt was created during these failed attempts
        self.assertEqual(Prompt.objects.count(), 0)

    def test_list_prompts_empty(self):
        """
        Ensure GET /api/prompts/ returns an empty list when no prompts exist.
        """
        url = reverse('api:prompt-list-create')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Assuming default pagination structure
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(len(response.data['results']), 0)

    def test_list_prompts_with_data(self):
        """
        Ensure GET /api/prompts/ returns a list of prompts and excludes modification_code.
        """
        # Create some prompts using the helper
        prompt1 = self._create_prompt(title="Prompt One", tags=["tag1", "common"])
        prompt2 = self._create_prompt(title="Prompt Two", tags=["tag2", "common"])
        prompt3 = self._create_prompt(title="Prompt Three", tags=["tag3"])

        url = reverse('api:prompt-list-create')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check pagination structure and counts
        self.assertEqual(response.data['count'], 3)
        # Assuming default page size is >= 3, otherwise adjust assertion
        self.assertEqual(len(response.data['results']), 3)

        # Check the structure and content of one of the results
        # Results are usually ordered by creation time (newest first by default in DRF)
        # Let's check the first result (should correspond to prompt3)
        first_result = response.data['results'][0]
        self.assertEqual(first_result['title'], prompt3.title)
        self.assertIn('prompt_id', first_result)
        self.assertIn('username', first_result)
        self.assertIn('tags', first_result)
        self.assertIn('comment_count', first_result) # Check for the count field
        self.assertEqual(first_result['comment_count'], 0) # Assuming no comments created yet

        # --- CRITICAL CHECK: Ensure modification_code is NOT present ---
        self.assertNotIn('modification_code', first_result)

        # Optional: Check another result to be sure
        second_result = response.data['results'][1]
        self.assertEqual(second_result['title'], prompt2.title)
        self.assertNotIn('modification_code', second_result)

    def test_list_prompts_filter_by_tag(self):
        """
        Ensure GET /api/prompts/ can be filtered by one or more tags.
        """
        # Create prompts with specific tags
        prompt_common = self._create_prompt(title="Common", tags=["tag1", "common"])
        prompt_tag1 = self._create_prompt(title="Only Tag1", tags=["tag1"])
        prompt_tag2 = self._create_prompt(title="Only Tag2", tags=["tag2"])
        prompt_both = self._create_prompt(title="Both Tags", tags=["tag1", "tag2"])

        base_url = reverse('api:prompt-list-create')

        # Test filtering by a single tag ('tag1')
        url_tag1 = f"{base_url}?tags=tag1"
        response_tag1 = self.client.get(url_tag1)
        self.assertEqual(response_tag1.status_code, status.HTTP_200_OK)
        self.assertEqual(response_tag1.data['count'], 3) # common, tag1, both
        # Check titles to be sure (order might vary depending on default ordering)
        titles_tag1 = {p['title'] for p in response_tag1.data['results']}
        self.assertSetEqual(titles_tag1, {"Common", "Only Tag1", "Both Tags"})

        # Test filtering by a different single tag ('tag2')
        url_tag2 = f"{base_url}?tags=tag2"
        response_tag2 = self.client.get(url_tag2)
        self.assertEqual(response_tag2.status_code, status.HTTP_200_OK)
        self.assertEqual(response_tag2.data['count'], 2) # tag2, both
        titles_tag2 = {p['title'] for p in response_tag2.data['results']}
        self.assertSetEqual(titles_tag2, {"Only Tag2", "Both Tags"})

        # Test filtering by a tag with no matches ('unknown')
        url_unknown = f"{base_url}?tags=unknown"
        response_unknown = self.client.get(url_unknown)
        self.assertEqual(response_unknown.status_code, status.HTTP_200_OK)
        self.assertEqual(response_unknown.data['count'], 0)
        self.assertEqual(len(response_unknown.data['results']), 0)

        # Test filtering by multiple tags (e.g., 'tag1' OR 'tag2' - using __overlap)
        url_tag1_tag2 = f"{base_url}?tags=tag1,tag2" # Comma-separated
        response_tag1_tag2 = self.client.get(url_tag1_tag2)
        self.assertEqual(response_tag1_tag2.status_code, status.HTTP_200_OK)

        # --- CORRECTED ASSERTION for OR logic (__overlap) ---
        # Expecting prompts with 'tag1' OR 'tag2' (or both)
        # prompt_common, prompt_tag1, prompt_tag2, prompt_both = 4 prompts
        self.assertEqual(response_tag1_tag2.data['count'], 4)
        # Optionally check titles
        titles_tag1_tag2 = {p['title'] for p in response_tag1_tag2.data['results']}
        self.assertSetEqual(titles_tag1_tag2, {"Common", "Only Tag1", "Only Tag2", "Both Tags"})
        # --- END CORRECTION ---


        # Test filtering by multiple tags where one doesn't exist ('tag1' OR 'unknown')
        url_tag1_unknown = f"{base_url}?tags=tag1,unknown"
        response_tag1_unknown = self.client.get(url_tag1_unknown)
        self.assertEqual(response_tag1_unknown.status_code, status.HTTP_200_OK)
        # --- CORRECTED ASSERTION for OR logic (__overlap) ---
        # Expecting prompts with 'tag1' (unknown matches nothing)
        # prompt_common, prompt_tag1, prompt_both = 3 prompts
        self.assertEqual(response_tag1_unknown.data['count'], 3)
        titles_tag1_unknown = {p['title'] for p in response_tag1_unknown.data['results']}
        self.assertSetEqual(titles_tag1_unknown, {"Common", "Only Tag1", "Both Tags"})
        # --- END CORRECTION ---

    def test_list_prompts_pagination(self):
        """
        Ensure GET /api/prompts/ is paginated correctly.
        Assumes a page size (e.g., 10). Adjust PAGE_SIZE if different.
        """
        PAGE_SIZE = 10 # Adjust if your settings.py defines a different PAGE_SIZE
        NUM_PROMPTS = PAGE_SIZE + 2 # Create more prompts than the page size

        # Create prompts
        for i in range(NUM_PROMPTS):
            self._create_prompt(title=f"Prompt {i+1}", tags=[f"page_test_{i}"])

        url = reverse('api:prompt-list-create')

        # --- Test First Page ---
        response_page1 = self.client.get(url)
        self.assertEqual(response_page1.status_code, status.HTTP_200_OK)

        # Check counts and structure
        self.assertEqual(response_page1.data['count'], NUM_PROMPTS)
        self.assertEqual(len(response_page1.data['results']), PAGE_SIZE)
        self.assertIsNotNone(response_page1.data['next'])
        self.assertIsNone(response_page1.data['previous'])
        # Check title of first item (assuming default ordering is newest first)
        self.assertEqual(response_page1.data['results'][0]['title'], f"Prompt {NUM_PROMPTS}")

        # --- Test Second Page ---
        next_url = response_page1.data['next']
        response_page2 = self.client.get(next_url)
        self.assertEqual(response_page2.status_code, status.HTTP_200_OK)

        # Check counts and structure
        self.assertEqual(response_page2.data['count'], NUM_PROMPTS)
        self.assertEqual(len(response_page2.data['results']), NUM_PROMPTS - PAGE_SIZE) # Remainder
        self.assertIsNone(response_page2.data['next'])
        self.assertIsNotNone(response_page2.data['previous'])
        # Check title of first item on page 2
        self.assertEqual(response_page2.data['results'][0]['title'], f"Prompt {NUM_PROMPTS - PAGE_SIZE}")

    def test_retrieve_prompt_success(self):
        """
        Ensure GET /api/prompts/{id}/ returns a single prompt and excludes modification_code.
        """
        prompt = self._create_prompt(title="Detail Test", tags=["detail"])
        # --- CHANGE 'pk' to 'prompt_id' ---
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt.prompt_id})
        # --- END CHANGE ---

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['prompt_id'], str(prompt.prompt_id))
        self.assertEqual(response.data['title'], "Detail Test")
        self.assertIn('content', response.data)
        self.assertIn('username', response.data)
        self.assertListEqual(response.data['tags'], ["detail"])
        self.assertIn('created_at', response.data)
        self.assertIn('updated_at', response.data)
        self.assertIn('comments', response.data) # Check the key exists

        # --- CORRECTED ASSERTION for paginated comments ---
        # Check the 'results' list within the 'comments' structure
        self.assertIsInstance(response.data['comments'], dict)
        self.assertIn('results', response.data['comments'])
        self.assertEqual(response.data['comments']['results'], [])
        self.assertEqual(response.data['comments']['count'], 0)
        # --- END CORRECTION ---

        # --- CRITICAL CHECK: Ensure modification_code is NOT present ---
        self.assertNotIn('modification_code', response.data)

    def test_retrieve_prompt_not_found(self):
        """
        Ensure GET /api/prompts/{id}/ returns 404 for a non-existent ID.
        """
        import uuid
        non_existent_uuid = uuid.uuid4()
        # --- CHANGE 'pk' to 'prompt_id' ---
        url = reverse('api:prompt-detail', kwargs={'prompt_id': non_existent_uuid})
        # --- END CHANGE ---

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_prompt_success(self):
        """
        Ensure PATCH /api/prompts/{id}/ updates a prompt with the correct modification code.
        """
        prompt = self._create_prompt(title="Original Title", content="Original content.", tags=["original"])
        mod_code = prompt.modification_code # Get the code from the created object
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt.prompt_id})

        update_data = {
            'title': 'Updated Title',
            'tags': ['updated', 'tag'],
            'modification_code': mod_code # Provide the correct code
        }

        response = self.client.patch(url, update_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify data in the database
        prompt.refresh_from_db()
        self.assertEqual(prompt.title, 'Updated Title')
        self.assertEqual(prompt.content, 'Original content.') # Content wasn't updated
        self.assertListEqual(sorted(prompt.tags), sorted(['updated', 'tag']))

        # Verify response data
        self.assertEqual(response.data['title'], 'Updated Title')
        self.assertListEqual(sorted(response.data['tags']), sorted(['updated', 'tag']))
        self.assertNotIn('modification_code', response.data) # Code shouldn't be in response

    def test_update_prompt_wrong_code(self):
        """
        Ensure PATCH /api/prompts/{id}/ fails with 403 if modification code is wrong.
        """
        prompt = self._create_prompt(title="Original Title")
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt.prompt_id})

        update_data = {
            'title': 'Updated Title Attempt',
            'modification_code': 'WRONGCODE' # Provide incorrect code
        }

        response = self.client.patch(url, update_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify data in the database was NOT changed
        prompt.refresh_from_db()
        self.assertEqual(prompt.title, 'Original Title')

    def test_update_prompt_missing_code(self):
        """
        Ensure PATCH /api/prompts/{id}/ fails with 403 if modification code is missing.
        """
        prompt = self._create_prompt(title="Original Title")
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt.prompt_id})

        update_data = {
            'title': 'Updated Title Attempt',
            # 'modification_code': '...' # Code is missing
        }

        response = self.client.patch(url, update_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify data in the database was NOT changed
        prompt.refresh_from_db()
        self.assertEqual(prompt.title, 'Original Title')

    def test_update_prompt_validation_error(self):
        """
        Ensure PATCH /api/prompts/{id}/ fails with 400 for invalid data, even with correct code.
        """
        prompt = self._create_prompt(title="Original Title")
        mod_code = prompt.modification_code
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt.prompt_id})

        invalid_data = {
            'title': '', # Invalid: empty title
            'tags': ['tag<script>'], # Invalid: bad characters
            'modification_code': mod_code # Correct code
        }

        response = self.client.patch(url, invalid_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data) # Check for title error
        self.assertIn('tags', response.data) # Check for tags error

        # Verify data in the database was NOT changed
        prompt.refresh_from_db()
        self.assertEqual(prompt.title, 'Original Title')

    def test_delete_prompt_success(self):
        """
        Ensure DELETE /api/prompts/{id}/ deletes a prompt with the correct modification code.
        """
        prompt = self._create_prompt(title="To Be Deleted")
        mod_code = prompt.modification_code
        prompt_id = prompt.prompt_id # Store ID before deletion
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt_id})

        delete_data = {
            'modification_code': mod_code # Provide the correct code
        }

        response = self.client.delete(url, delete_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify the prompt is actually deleted from the database
        with self.assertRaises(Prompt.DoesNotExist):
            Prompt.objects.get(prompt_id=prompt_id)

    def test_delete_prompt_wrong_code(self):
        """
        Ensure DELETE /api/prompts/{id}/ fails with 403 if modification code is wrong.
        """
        prompt = self._create_prompt(title="Not Deleted")
        prompt_id = prompt.prompt_id
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt_id})

        delete_data = {
            'modification_code': 'WRONGCODE' # Provide incorrect code
        }

        response = self.client.delete(url, delete_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify the prompt still exists in the database
        self.assertTrue(Prompt.objects.filter(prompt_id=prompt_id).exists())

    def test_delete_prompt_missing_code(self):
        """
        Ensure DELETE /api/prompts/{id}/ fails with 403 if modification code is missing.
        """
        prompt = self._create_prompt(title="Not Deleted")
        prompt_id = prompt.prompt_id
        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt_id})

        # delete_data = {} # No data sent, or data without the code

        response = self.client.delete(url, format='json') # Send request without data body

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify the prompt still exists in the database
        self.assertTrue(Prompt.objects.filter(prompt_id=prompt_id).exists())

    def test_delete_prompt_not_found(self):
        """
        Ensure DELETE /api/prompts/{id}/ fails with 404 for a non-existent ID.
        """
        import uuid
        non_existent_uuid = uuid.uuid4()
        url = reverse('api:prompt-detail', kwargs={'prompt_id': non_existent_uuid})

        delete_data = {
            'modification_code': 'ANYCODE' # Code doesn't matter if ID is wrong
        }

        response = self.client.delete(url, delete_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_prompt_with_comments(self):
        """
        Ensure GET /api/prompts/{id}/ includes associated comments in the response.
        """
        prompt = self._create_prompt(title="Prompt With Comments")
        # Create comments associated with the prompt
        comment1 = Comment.objects.create(prompt=prompt, content="First comment")
        comment2 = Comment.objects.create(prompt=prompt, content="Second comment", username="Commenter")

        url = reverse('api:prompt-detail', kwargs={'prompt_id': prompt.prompt_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('comments', response.data)
        self.assertIsInstance(response.data['comments'], dict) # Check pagination structure
        self.assertEqual(response.data['comments']['count'], 2)
        self.assertEqual(len(response.data['comments']['results']), 2)

        # Check details of the comments in the response (order might vary)
        response_comments = response.data['comments']['results']
        response_contents = {c['content'] for c in response_comments}
        self.assertSetEqual(response_contents, {"First comment", "Second comment"})

        # Ensure modification_code is NOT in the nested comment data
        self.assertNotIn('modification_code', response_comments[0])
        self.assertNotIn('modification_code', response_comments[1])

        # ... inside PromptAPITests class ...

    def test_list_prompts_filter_by_multiple_tags_overlap(self):
        """
        Ensure GET /api/prompts/?tags=tag1,tag2 returns prompts matching ANY of the tags.
        """
        # Create prompts with different tag combinations
        p1 = self._create_prompt(title="Overlap 1", tags=["python", "api"])
        p2 = self._create_prompt(title="Overlap 2", tags=["django", "python"])
        p3 = self._create_prompt(title="Overlap 3", tags=["api", "test"])
        p4 = self._create_prompt(title="Overlap 4", tags=["javascript"]) # Should not match

        # Filter for prompts containing either 'python' OR 'api'
        url = reverse('api:prompt-list-create') + '?tags=python,api'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3) # p1, p2, p3 should match

        results = response.data['results']
        retrieved_ids = {item['prompt_id'] for item in results}
        expected_ids = {str(p1.prompt_id), str(p2.prompt_id), str(p3.prompt_id)}
        self.assertSetEqual(retrieved_ids, expected_ids)

        # Test with tags that have no overlap
        url_no_match = reverse('api:prompt-list-create') + '?tags=java,ruby'
        response_no_match = self.client.get(url_no_match)
        self.assertEqual(response_no_match.status_code, status.HTTP_200_OK)
        self.assertEqual(response_no_match.data['count'], 0) # No prompts should match

    # --- End of Prompt API Tests ---


# --- Comment API Tests ---

# Keep the override_settings here for the new class too
@override_settings(SILENCED_SYSTEM_CHECKS=["django_ratelimit.W001"])
class CommentAPITests(APITestCase):
    """
    Tests for the /api/prompts/{prompt_id}/comments/ endpoint.
    """

    def setUp(self):
        """Create a prompt to associate comments with."""
        self.prompt = Prompt.objects.create(title="Test Prompt for Comments", content="...")
        # --- Use the CORRECT URL name ---
        # Replace 'prompt-comment-list-create' with the actual name from urls.py
        # Example: Assuming the name is 'comment-list-create'
        self.base_url = reverse('api:comment-list-create', kwargs={'prompt_id': self.prompt.prompt_id})
        # --- END CHANGE ---

    def test_create_comment_success(self):
        """
        Ensure POST /api/prompts/{prompt_id}/comments/ creates a comment.
        """
        data = {
            'content': 'This is a test comment.',
            'username': 'TestUser'
            # modification_code is optional on creation
        }
        response = self.client.post(self.base_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Comment.objects.count(), 1)
        comment = Comment.objects.first()
        self.assertEqual(comment.prompt, self.prompt)
        self.assertEqual(comment.content, 'This is a test comment.')
        self.assertEqual(comment.username, 'TestUser')
        self.assertIsNotNone(comment.modification_code) # Check code was generated

        # Check response data
        self.assertEqual(response.data['content'], 'This is a test comment.')
        self.assertEqual(response.data['username'], 'TestUser')
        self.assertIn('comment_id', response.data)
        self.assertIn('created_at', response.data)
        self.assertIn('modification_code', response.data) # Code should be in create response

    def test_create_comment_missing_content(self):
        """
        Ensure POST fails with 400 if content is missing.
        """
        data = {
            'username': 'TestUser'
            # 'content': '...' # Missing
        }
        response = self.client.post(self.base_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', response.data) # Check for content error
        self.assertEqual(Comment.objects.count(), 0)

    def test_create_comment_strip_html(self):
        """
        Ensure POST strips HTML from comment content using bleach.
        """
        data = {
            'content': 'This is <b>bold</b> and <script>alert("bad")</script> comment.',
            'username': 'HTMLUser'
        }
        response = self.client.post(self.base_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Comment.objects.count(), 1)
        comment = Comment.objects.first()
        # Check content in DB is sanitized
        self.assertEqual(comment.content, 'This is bold and alert("bad") comment.')
        # Check content in response is sanitized
        self.assertEqual(response.data['content'], 'This is bold and alert("bad") comment.')

    # --- Helper to create a comment ---
    def _create_comment(self, content="Test Comment", username=None):
        return Comment.objects.create(prompt=self.prompt, content=content, username=username)

    def test_update_comment_success(self):
        """
        Ensure PATCH /api/comments/{id}/ updates a comment with the correct code.
        """
        comment = self._create_comment(content="Original Comment")
        mod_code = comment.modification_code
        url = reverse('api:comment-detail', kwargs={'comment_id': comment.comment_id})

        update_data = {
            'content': 'Updated Comment Content',
            'modification_code': mod_code
        }
        response = self.client.patch(url, update_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        comment.refresh_from_db()
        self.assertEqual(comment.content, 'Updated Comment Content')
        self.assertEqual(response.data['content'], 'Updated Comment Content')
        self.assertNotIn('modification_code', response.data) # Code shouldn't be in response

    def test_update_comment_wrong_code(self):
        """
        Ensure PATCH /api/comments/{id}/ fails with 403 for wrong code.
        """
        comment = self._create_comment(content="Original Comment")
        url = reverse('api:comment-detail', kwargs={'comment_id': comment.comment_id})
        update_data = {'content': 'Update Attempt', 'modification_code': 'WRONG'}
        response = self.client.patch(url, update_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        comment.refresh_from_db()
        self.assertEqual(comment.content, 'Original Comment') # Check not changed

    def test_update_comment_missing_code(self):
        """
        Ensure PATCH /api/comments/{id}/ fails with 403 for missing code.
        """
        comment = self._create_comment(content="Original Comment")
        url = reverse('api:comment-detail', kwargs={'comment_id': comment.comment_id})
        update_data = {'content': 'Update Attempt'} # Missing code
        response = self.client.patch(url, update_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_comment_success(self):
        """
        Ensure DELETE /api/comments/{id}/ deletes a comment with the correct code.
        """
        comment = self._create_comment()
        mod_code = comment.modification_code
        comment_id = comment.comment_id
        url = reverse('api:comment-detail', kwargs={'comment_id': comment_id})
        delete_data = {'modification_code': mod_code}
        response = self.client.delete(url, delete_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        with self.assertRaises(Comment.DoesNotExist):
            Comment.objects.get(comment_id=comment_id)

    def test_delete_comment_wrong_code(self):
        """
        Ensure DELETE /api/comments/{id}/ fails with 403 for wrong code.
        """
        comment = self._create_comment()
        comment_id = comment.comment_id
        url = reverse('api:comment-detail', kwargs={'comment_id': comment_id})
        delete_data = {'modification_code': 'WRONG'}
        response = self.client.delete(url, delete_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Comment.objects.filter(comment_id=comment_id).exists())

    def test_delete_comment_missing_code(self):
        """
        Ensure DELETE /api/comments/{id}/ fails with 403 for missing code.
        """
        comment = self._create_comment()
        comment_id = comment.comment_id
        url = reverse('api:comment-detail', kwargs={'comment_id': comment_id})
        response = self.client.delete(url, format='json') # No data body
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Comment.objects.filter(comment_id=comment_id).exists())

    def test_create_comment_non_existent_prompt(self):
        """
        Ensure POST /api/prompts/{bad_id}/comments/ returns 404.
        """
        import uuid
        non_existent_uuid = uuid.uuid4()
        # Construct URL with a UUID that doesn't exist
        bad_url = reverse('api:comment-list-create', kwargs={'prompt_id': non_existent_uuid})

        data = {
            'content': 'This comment should not be created.',
            'username': 'GhostUser'
        }
        response = self.client.post(bad_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Comment.objects.count(), 0) # Ensure no comment was created

    def test_list_comments_non_existent_prompt(self):
        """
        Ensure GET /api/prompts/{bad_id}/comments/ returns 404.
        """
        import uuid
        non_existent_uuid = uuid.uuid4()
        # Construct URL with a UUID that doesn't exist
        bad_url = reverse('api:comment-list-create', kwargs={'prompt_id': non_existent_uuid})

        response = self.client.get(bad_url) # Use GET request

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- End Comment API Tests ---

# --- Random Prompt View Tests ---

class RandomPromptViewTests(APITestCase):
    """
    Tests for the /api/prompts/random/ endpoint.
    """

    def _create_prompt(self, title="Sample Title", content="Sample content.", tags=None):
        """Helper method copied from PromptAPITests for convenience."""
        if tags is None:
            tags = ["sample", "test"]
        return Prompt.objects.create(title=title, content=content, tags=tags)

    def test_get_random_prompt_success(self):
        """
        Ensure GET /api/prompts/random/ returns a valid prompt when prompts exist.
        """
        # Create a few prompts
        p1 = self._create_prompt(title="Random 1")
        p2 = self._create_prompt(title="Random 2")
        p3 = self._create_prompt(title="Random 3")
        prompt_ids = {str(p.prompt_id) for p in [p1, p2, p3]}

        url = reverse('api:prompt-random')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check that the response looks like a prompt detail
        self.assertIn('prompt_id', response.data)
        self.assertIn('title', response.data)
        self.assertIn('content', response.data)
        self.assertIn('username', response.data)
        self.assertIn('tags', response.data)
        self.assertIn('comments', response.data)
        self.assertNotIn('modification_code', response.data)

        # Check that the returned prompt ID is one of the ones we created
        self.assertIn(response.data['prompt_id'], prompt_ids)

        # Optional: Call it again and check if it's potentially different
        # (Not a guarantee, but increases confidence it's random)
        # response2 = self.client.get(url)
        # self.assertEqual(response2.status_code, status.HTTP_200_OK)
        # self.assertIn(response2.data['prompt_id'], prompt_ids)

    def test_get_random_prompt_no_prompts(self):
        """
        Ensure GET /api/prompts/random/ returns 404 when no prompts exist.
        """
        # Ensure database is empty
        self.assertEqual(Prompt.objects.count(), 0)

        url = reverse('api:prompt-random')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

# --- End Random Prompt View Tests ---

# --- Batch Prompt View Tests (FOR RETRIEVAL) ---

class BatchPromptViewTests(APITestCase):
    """
    Tests for the /api/prompts/batch/ endpoint (Batch Retrieval).
    """

    def _create_prompt(self, title="Sample Title", content="Sample content.", tags=None):
        """Helper method copied from PromptAPITests for convenience."""
        if tags is None:
            tags = ["sample", "test"]
        return Prompt.objects.create(title=title, content=content, tags=tags)

    def test_batch_retrieve_success(self):
        """
        Ensure POST /api/prompts/batch/ retrieves multiple prompts by ID successfully.
        """
        p1 = self._create_prompt(title="Batch Retrieve 1")
        p2 = self._create_prompt(title="Batch Retrieve 2")
        p3 = self._create_prompt(title="Batch Retrieve 3 (Not requested)") # Extra prompt

        url = reverse('api:prompt-batch')
        # Send the IDs of the prompts we want to retrieve
        data = {'ids': [str(p1.prompt_id), str(p2.prompt_id)]}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        # Should return only the 2 requested prompts
        self.assertEqual(len(response.data), 2)

        # Check the IDs in the response
        retrieved_ids = {item['prompt_id'] for item in response.data}
        self.assertSetEqual(retrieved_ids, {str(p1.prompt_id), str(p2.prompt_id)})

        # Check that the response uses the PromptListSerializer structure (includes comment_count)
        self.assertIn('comment_count', response.data[0])
        self.assertNotIn('modification_code', response.data[0]) # Should not be included

    def test_batch_retrieve_some_invalid_ids(self):
        """
        Ensure POST /api/prompts/batch/ retrieves only valid IDs if some are invalid/not found.
        """
        import uuid
        p1 = self._create_prompt(title="Batch Retrieve Valid")
        non_existent_uuid = uuid.uuid4()

        url = reverse('api:prompt-batch')
        data = {'ids': [str(p1.prompt_id), str(non_existent_uuid), "not-a-uuid"]}
        response = self.client.post(url, data, format='json')

        # The view should still return 200 OK, but only include the valid prompt found
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1) # Only p1 should be found
        self.assertEqual(response.data[0]['prompt_id'], str(p1.prompt_id))

    def test_batch_retrieve_no_valid_ids(self):
        """
        Ensure POST /api/prompts/batch/ returns an empty list if no valid IDs are found.
        """
        import uuid
        non_existent_uuid1 = uuid.uuid4()
        non_existent_uuid2 = uuid.uuid4()

        url = reverse('api:prompt-batch')
        data = {'ids': [str(non_existent_uuid1), str(non_existent_uuid2)]}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 0) # Empty list expected

    def test_batch_retrieve_empty_id_list(self):
        """
        Ensure POST /api/prompts/batch/ returns an empty list if the 'ids' list is empty.
        """
        url = reverse('api:prompt-batch')
        data = {'ids': []} # Empty list of IDs
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 0)

    def test_batch_retrieve_missing_ids_key(self):
        """
        Ensure POST /api/prompts/batch/ returns 400 if the 'ids' key is missing.
        """
        url = reverse('api:prompt-batch')
        data = {'something_else': []} # Missing 'ids' key
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ids', response.data) # Error should mention the 'ids' field

    def test_batch_retrieve_ids_not_a_list(self):
        """
        Ensure POST /api/prompts/batch/ returns 400 if 'ids' is not a list.
        """
        url = reverse('api:prompt-batch')
        data = {'ids': "not-a-list"} # 'ids' is a string, not a list
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ids', response.data)

# --- End Batch Prompt View Tests ---

# --- Tag List View Tests ---

class TagListViewTests(APITestCase):
    """
    Tests for the /api/tags/ endpoint.
    """

    def _create_prompt(self, title="Sample Title", content="Sample content.", tags=None):
        """Helper method copied from PromptAPITests for convenience."""
        # Default to None to test that case
        return Prompt.objects.create(title=title, content=content, tags=tags)

    def test_list_tags_success(self):
        """
        Ensure GET /api/tags/ returns a sorted list of unique tags.
        """
        # Create prompts with various tags
        self._create_prompt(title="P1", tags=["python", "api", "test"])
        self._create_prompt(title="P2", tags=["django", "python"])
        self._create_prompt(title="P3", tags=["test", "example"])
        self._create_prompt(title="P4", tags=["python"]) # Duplicate tag
        self._create_prompt(title="P5", tags=[]) # Empty list
        self._create_prompt(title="P6", tags=None) # Null tags
        self._create_prompt(title="P7", tags=["API"]) # Different case

        url = reverse('api:tag-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

        # Expected unique tags, sorted alphabetically, case-insensitively merged
        # Note: Your view currently doesn't handle case-insensitivity merging,
        # it treats 'api' and 'API' as distinct based on the code.
        # Let's test the current behavior first.
        expected_tags = sorted(["API", "api", "django", "example", "python", "test"])
        self.assertListEqual(response.data, expected_tags)

    def test_list_tags_no_tags_exist(self):
        """
        Ensure GET /api/tags/ returns an empty list if no prompts have tags.
        """
        # Create prompts with no tags or null tags
        self._create_prompt(title="No Tags 1", tags=[])
        self._create_prompt(title="No Tags 2", tags=None)

        url = reverse('api:tag-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 0) # Expect empty list

    def test_list_tags_no_prompts_exist(self):
        """
        Ensure GET /api/tags/ returns an empty list if no prompts exist at all.
        """
        # Ensure no prompts exist
        self.assertEqual(Prompt.objects.count(), 0)

        url = reverse('api:tag-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 0) # Expect empty list

# --- End Tag List View Tests ---

# --- API Root View Tests ---

class ApiRootViewTests(APITestCase):
    """
    Tests for the /api/ endpoint.
    """

    def test_api_root_success(self):
        """
        Ensure GET /api/ returns 200 OK and expected structure when DB is connected.
        """
        url = reverse('api:api-root')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check for expected keys in the response
        self.assertIn('status', response.data)
        self.assertIn('message', response.data)
        self.assertIn('database_connection', response.data)

        # Check specific values
        self.assertEqual(response.data['status'], 'ok')
        self.assertEqual(response.data['database_connection'], 'ok')
        self.assertEqual(response.data['message'], 'PromptBase API is running.')

        # Ensure no assertions for 'endpoints' remain here

    # Note: Testing the OperationalError case (lines 424-428) is difficult
    # in a standard unit test setup as it requires simulating a DB connection failure.
    # This is often tested manually or via integration tests.

# --- End API Root View Tests ---

# --- Cache Test View Tests ---

class CacheTestViewTests(APITestCase):
    """
    Tests for the /api/cache-test/ endpoint.
    """
    def setUp(self):
        """Clear cache before each test."""
        cache.clear()

    def tearDown(self):
        """Clear cache after each test."""
        cache.clear()

    def test_cache_get_miss(self):
        """
        Ensure GET returns 'Cache miss' when key is not set.
        """
        url = reverse('api:cache-test') + '?key=mytestkey'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'status': 'Cache miss', 'key': 'mytestkey'})

    def test_cache_set_and_get_hit(self):
        """
        Ensure POST sets a value and GET retrieves it (Cache hit).
        """
        url = reverse('api:cache-test')
        key = 'mytestkey'
        value = 'mytestvalue'

        # POST to set the value
        post_data = {'key': key, 'value': value}
        post_response = self.client.post(url, post_data, format='json')
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(post_response.data, {'status': 'Cache set', 'key': key, 'value': value})

        # GET to retrieve the value
        get_url = f"{url}?key={key}"
        get_response = self.client.get(get_url)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data, {'status': 'Cache hit', 'key': key, 'value': value})

    def test_cache_delete(self):
        """
        Ensure DELETE removes a key from the cache.
        """
        url = reverse('api:cache-test')
        key = 'mytestkey_to_delete'
        value = 'somevalue'

        # Set the value first
        cache.set(key, value, timeout=60)
        self.assertEqual(cache.get(key), value) # Verify it's set

        # DELETE the key
        delete_url = f"{url}?key={key}"
        delete_response = self.client.delete(delete_url)
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_response.data, {'status': 'Cache deleted', 'key': key})

        # Verify the key is gone from cache
        self.assertIsNone(cache.get(key))

        # Try deleting a non-existent key
        delete_non_existent_url = f"{url}?key=nonexistentkey"
        delete_non_existent_response = self.client.delete(delete_non_existent_url)
        self.assertEqual(delete_non_existent_response.status_code, status.HTTP_200_OK) # Should still be OK
        self.assertEqual(delete_non_existent_response.data, {'status': 'Cache key not found or already deleted', 'key': 'nonexistentkey'})


    def test_cache_missing_key_param(self):
        """
        Ensure GET and DELETE return 400 if 'key' query parameter is missing.
        """
        url = reverse('api:cache-test') # No query param

        # Test GET
        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', get_response.data)
        self.assertEqual(get_response.data['error'], 'Missing key query parameter')

        # Test DELETE
        delete_response = self.client.delete(url)
        self.assertEqual(delete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', delete_response.data)
        self.assertEqual(delete_response.data['error'], 'Missing key query parameter')

    def test_cache_missing_post_data(self):
        """
        Ensure POST returns 400 if 'key' or 'value' is missing in the body.
        """
        url = reverse('api:cache-test')

        # Missing value
        response_no_value = self.client.post(url, {'key': 'somekey'}, format='json')
        self.assertEqual(response_no_value.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response_no_value.data)
        self.assertEqual(response_no_value.data['error'], 'Missing key or value in request body')

        # Missing key
        response_no_key = self.client.post(url, {'value': 'somevalue'}, format='json')
        self.assertEqual(response_no_key.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response_no_key.data)
        self.assertEqual(response_no_key.data['error'], 'Missing key or value in request body')

        # Empty body
        response_empty = self.client.post(url, {}, format='json')
        self.assertEqual(response_empty.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response_empty.data)
        self.assertEqual(response_empty.data['error'], 'Missing key or value in request body')

# --- End Cache Test View Tests ---
