# Batch Runner Setup
The batch utility natively matches Column 0 (Prompt ID) and groups variants into a pairwise-compatible evaluation struct. Ensure that the 'Model' parameter provides either the specific model slug (e.g. `veo-3-1-preview-i2v`) or if left blank / generic, it acts as a scatter-shot that queues *all active models* for the respective mode!
