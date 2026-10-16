"""storyGenerationService — 与 backend-node/src/services/storyGenerationService.js 1:1 对齐。"""
from app.services.generationService import (
    generate_story,
    process_story_generation,
    start_story_generation,
)

# 驼峰别名与 Node 兼容
generateStory = generate_story
startStoryGeneration = start_story_generation
processStoryGeneration = process_story_generation
