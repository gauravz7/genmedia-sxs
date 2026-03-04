import os
import re

files = [
    "/Users/gauravz/Desktop/Antigravity/SxS/project-pulse/frontend/src/app/page.tsx",
    "/Users/gauravz/Desktop/Antigravity/SxS/project-pulse/frontend/src/app/admin/page.tsx"
]

for filepath in files:
    with open(filepath, "r") as f:
        content = f.read()

    # Inject the constant definition
    if "const API_BASE_URL" not in content:
        content = content.replace(
            "'use client';",
            "'use client';\nconst API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || \"http://127.0.0.1:8011\";"
        )

    # regex to replace different quote styles of the URL
    content = re.sub(r'\"http://127\.0\.0\.1:8011([^\"]*)\"', r'`${API_BASE_URL}\1`', content)
    content = re.sub(r'\'http://127\.0\.0\.1:8011([^\']*)\'', r'`${API_BASE_URL}\1`', content)
    content = re.sub(r'`http://127\.0\.0\.1:8011([^`]*)`', r'`${API_BASE_URL}\1`', content)
    
    with open(filepath, "w") as f:
        f.write(content)
