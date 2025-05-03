import json
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from api.models import Prompt, Comment # Adjust the import path if your models are elsewhere

class Command(BaseCommand):
    help = 'Seeds the database with initial data from seed_data.json'

    def handle(self, *args, **options):
        # Get the directory of the current script and join with the filename
        script_dir = os.path.dirname(__file__)
        seed_file_path = os.path.join(script_dir, 'seed_data.json')

        if not os.path.exists(seed_file_path):
            self.stdout.write(self.style.ERROR(f"Seed file not found at {seed_file_path}"))
            return

        with open(seed_file_path, 'r') as f:
            data = json.load(f)

        # Clear existing data (optional, but recommended for repeatable seeding)
        self.stdout.write("Clearing existing Prompt and Comment data...")
        Comment.objects.all().delete() # Delete comments first due to FK
        Prompt.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Existing data cleared."))

        prompts_data = data.get('prompts', [])
        comments_data = data.get('comments', [])
        created_prompts = {} # To map title to prompt object for linking comments

        # Create Prompts
        self.stdout.write(f"Creating {len(prompts_data)} prompts...")
        for prompt_data in prompts_data:
            try:
                prompt = Prompt.objects.create(
                    title=prompt_data['title'],
                    content=prompt_data['content'],
                    tags=prompt_data.get('tags', []) # Use .get for optional tags
                )
                created_prompts[prompt.title] = prompt
                self.stdout.write(f"  Created prompt: {prompt.title}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error creating prompt '{prompt_data.get('title', 'N/A')}': {e}"))
        self.stdout.write(self.style.SUCCESS("Prompts created."))

        # Create Comments
        self.stdout.write(f"Creating {len(comments_data)} comments...")
        for comment_data in comments_data:
            prompt_title = comment_data.get('prompt_title')
            prompt_instance = created_prompts.get(prompt_title)

            if not prompt_instance:
                self.stdout.write(self.style.WARNING(f"  Skipping comment: Prompt '{prompt_title}' not found or wasn't created."))
                continue

            try:
                Comment.objects.create(
                    prompt=prompt_instance,
                    content=comment_data['content']
                )
                self.stdout.write(f"  Created comment for: {prompt_title}")
            except Exception as e:
                 self.stdout.write(self.style.ERROR(f"  Error creating comment for '{prompt_title}': {e}"))

        self.stdout.write(self.style.SUCCESS("Database seeding completed."))
