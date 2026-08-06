"""Gemini auto-tagging for jobs and prompts, run as a background task.

Shared by the admin prompt endpoints and the legacy generation flow.
"""

from providers.vertex_provider import generate_tags_with_gemini
from store import jobs_manager, prompts_manager


async def _auto_tag_job(job_id: str, prompt: str, start_image_url: str = None, end_image_url: str = None, reference_images: list = None):
    """Auto-generate tags for a job using Gemini, then persist them."""
    try:
        tags = await generate_tags_with_gemini(prompt, start_image_url, end_image_url, reference_images)
        job = jobs_manager.jobs.get(job_id)
        if job and not job.categories:
            job.categories = tags
            jobs_manager.save_job(job)
            print(f"Auto-tagged job {job_id}: {tags}")
    except Exception as e:
        print(f"Error auto-tagging job {job_id}: {e}")


async def _auto_tag_prompt(prompt_id: str, text: str, start_image_url: str = None, end_image_url: str = None, reference_images: list = None):
    """Auto-generate tags for a prompt using Gemini, then persist them."""
    try:
        tags = await generate_tags_with_gemini(text, start_image_url, end_image_url, reference_images)
        prompts = prompts_manager.prompts
        prompt = prompts.get(prompt_id)
        if prompt and not prompt.categories:
            prompt.categories = tags
            prompts_manager.save_prompt(prompt)
            print(f"Auto-tagged prompt {prompt_id}: {tags}")
    except Exception as e:
        print(f"Error auto-tagging prompt {prompt_id}: {e}")
