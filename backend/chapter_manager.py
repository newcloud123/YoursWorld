import re
import json
import os
from backend.config import CHAPTER_PATTERNS, NOVELS_DIR, MAX_CHAPTER_CONTENT_LENGTH
from backend.models import ChapterInfo


def split_chapters(text: str) -> list[dict]:
    """Split novel text into chapters using regex patterns.

    Returns list of dicts: { index, title, content, start_pos, end_pos }
    """
    combined_pattern = "|".join(f"({p})" for p in CHAPTER_PATTERNS)

    # Find all chapter header positions
    matches = []
    for m in re.finditer(combined_pattern, text, re.MULTILINE):
        matches.append((m.start(), m.group().strip()))

    if not matches:
        # No chapter headers found, treat entire text as one chapter
        return [{
            "index": 0,
            "title": "全文",
            "content": text,
            "start_pos": 0,
            "end_pos": len(text),
        }]

    chapters = []
    for i, (pos, title) in enumerate(matches):
        end_pos = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        content = text[pos:end_pos].strip()
        # Remove the chapter title from content to avoid duplication
        content_after_title = content[len(title):].strip()
        chapters.append({
            "index": i,
            "title": title,
            "content": content_after_title if content_after_title else content,
            "start_pos": pos,
            "end_pos": end_pos,
        })

    # If there's text before the first chapter, prepend it
    if matches[0][0] > 0:
        preamble = text[:matches[0][0]].strip()
        if preamble and len(preamble) > 50:  # Only if substantial
            chapters.insert(0, {
                "index": 0,
                "title": "序章",
                "content": preamble,
                "start_pos": 0,
                "end_pos": matches[0][0],
            })
            # Re-index
            for i, ch in enumerate(chapters):
                ch["index"] = i

    return chapters


def build_chapter_info(chapter: dict) -> ChapterInfo:
    """Build a ChapterInfo from a raw chapter dict."""
    content = chapter["content"]
    preview = content[:200] + "..." if len(content) > 200 else content
    return ChapterInfo(
        id=f"ch_{chapter['index']}",
        index=chapter["index"],
        title=chapter["title"],
        content_preview=preview,
    )


async def summarize_chapter(chapter: dict, llm_func) -> str:
    """Generate a chapter summary using LLM.

    Args:
        chapter: dict with 'title' and 'content'
        llm_func: async function(prompt, system_prompt) -> str
    """
    content = chapter["content"]
    if len(content) > MAX_CHAPTER_CONTENT_LENGTH:
        content = content[:MAX_CHAPTER_CONTENT_LENGTH] + "\n...(内容过长已截断)"

    prompt = (
        f"请用2-3句话概括以下小说章节的主要内容，包括关键事件和出场人物：\n\n"
        f"【{chapter['title']}】\n{content}"
    )
    try:
        summary = await llm_func(prompt, "你是一个小说分析助手，请简洁准确地概括章节内容。")
        return summary.strip()
    except Exception as e:
        print(f"Chapter summary failed for '{chapter['title']}': {e}")
        return ""


def get_novel_dir(novel_id: str) -> str:
    """Get the data directory for a specific novel."""
    return os.path.join(NOVELS_DIR, novel_id)


def save_chapters(novel_id: str, chapters: list[ChapterInfo]):
    """Save chapter list to novel's chapters.json."""
    novel_dir = get_novel_dir(novel_id)
    os.makedirs(novel_dir, exist_ok=True)
    path = os.path.join(novel_dir, "chapters.json")
    data = [ch.model_dump() for ch in chapters]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_chapters(novel_id: str) -> list[dict]:
    """Load chapter list from novel's chapters.json."""
    path = os.path.join(get_novel_dir(novel_id), "chapters.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def get_chapter_content(novel_id: str, chapter_index: int) -> str:
    """Get the raw text content of a specific chapter."""
    chapters = load_chapters(novel_id)
    if 0 <= chapter_index < len(chapters):
        # Content is stored in chapters.json during extraction
        # But for large novels, we need to re-read from the raw file
        raw_path = os.path.join(get_novel_dir(novel_id), "raw.txt")
        if os.path.exists(raw_path):
            with open(raw_path, "r", encoding="utf-8") as f:
                text = f.read()
            split = split_chapters(text)
            if 0 <= chapter_index < len(split):
                return split[chapter_index]["content"]
    return ""
