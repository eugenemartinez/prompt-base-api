import json
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from api.models import Prompt, Comment # Adjust the import path if your models are elsewhere

class Command(BaseCommand):
    help = 'Seeds the database with initial data from seed_data.json'

    def handle(self, *args, **options):
        script_dir = os.path.dirname(__file__)
        seed_file_path = os.path.join(script_dir, 'seed_data.json')

        if not os.path.exists(seed_file_path):
            self.stdout.write(self.style.ERROR(f"Seed file not found at {seed_file_path}"))
            return

        with open(seed_file_path, 'r') as f:
            data = json.load(f)

        self.stdout.write("Clearing existing Prompt and Comment data...")
        Comment.objects.all().delete()
        Prompt.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Existing data cleared."))

        prompts_data = data.get('prompts', [])
        comments_data = data.get('comments', [])
        # --- CHANGE: Store prompts by their actual DB ID ---
        created_prompts_by_id = {}

        # Create Prompts
        self.stdout.write(f"Creating {len(prompts_data)} prompts...")
        # --- CHANGE: Keep track of the order/intended ID ---
        intended_id_counter = 1
        for prompt_data in prompts_data:
            try:
                prompt = Prompt.objects.create(
                    title=prompt_data['title'],
                    content=prompt_data['content'],
                    tags=prompt_data.get('tags', [])
                )
                # --- CHANGE: Map the intended ID (from JSON) to the created prompt object ---
                # We assume the order in the JSON corresponds to IDs 1, 2, 3...
                created_prompts_by_id[intended_id_counter] = prompt
                self.stdout.write(f"  Created prompt (Intended ID {intended_id_counter}): {prompt.title}")
                intended_id_counter += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error creating prompt '{prompt_data.get('title', 'N/A')}': {e}"))
        self.stdout.write(self.style.SUCCESS("Prompts created."))

        # Create Comments
        self.stdout.write(f"Creating {len(comments_data)} comments...")
        for comment_data in comments_data:
            # --- CHANGE: Get the prompt_id from the JSON data ---
            prompt_id_from_json = comment_data.get('prompt_id')
            # --- CHANGE: Look up the prompt object using the ID ---
            prompt_instance = created_prompts_by_id.get(prompt_id_from_json)

            if not prompt_instance:
                # --- CHANGE: Update warning message ---
                self.stdout.write(self.style.WARNING(f"  Skipping comment: Prompt with intended ID '{prompt_id_from_json}' not found or wasn't created."))
                continue

            try:
                Comment.objects.create(
                    prompt=prompt_instance,
                    content=comment_data['content']
                )
                # --- CHANGE: Update success message ---
                self.stdout.write(f"  Created comment for prompt ID {prompt_id_from_json} ('{prompt_instance.title}')")
            except Exception as e:
                 # --- CHANGE: Update error message ---
                 self.stdout.write(self.style.ERROR(f"  Error creating comment for prompt ID {prompt_id_from_json}: {e}"))

        self.stdout.write(self.style.SUCCESS("Database seeding completed."))
