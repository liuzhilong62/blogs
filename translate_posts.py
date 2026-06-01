#!/usr/bin/env python3
"""Translate Chinese blog posts to English .en.md files."""

import re
import os
import sys
import time
from deep_translator import GoogleTranslator

BASE_DIR = "/Users/liuzhilong62/Documents/01-mygithub/blogs/content/posts"

FILES = [
    "PostgreSQL案例/2025-01-04-PG停库逻辑和walsender阻止停库问题分析.md",
    "PostgreSQL案例/2025-01-04-PG起库逻辑和spill导致起库慢问题分析.md",
    "PostgreSQL内功修炼/2024-08-12-PostgreSQL本地化.md",
    "PostgreSQL内功修炼/2024-08-12-向量数据库：从0到original paper.md",
    "PostgreSQL内功修炼/2025-12-13-从collation mismatch异常到其原理.md",
]

def split_content(text):
    """Split markdown into segments: text, code blocks, inline code, images, math, frontmatter."""
    segments = []
    # Pattern matches: fenced code blocks, inline code, images, math blocks, math inline
    pattern = re.compile(
        r'(```[^`]*```)|'           # fenced code blocks
        r'(`[^`]+`)|'               # inline code
        r'(!\[.*?\]\([^)]+\))|'     # images
        r'(\$\$[^$]+\$\$)|'         # display math
        r'(\$[^$]+\$)'             # inline math (single $)
    )
    
    last_end = 0
    for m in pattern.finditer(text):
        start, end = m.span()
        if start > last_end:
            segments.append(('text', text[last_end:start]))
        segments.append(('keep', m.group()))
        last_end = end
    
    if last_end < len(text):
        segments.append(('text', text[last_end:]))
    
    return segments

def translate_text(text, translator):
    """Translate Chinese text to English in chunks."""
    if not text or not text.strip():
        return text
    
    # Skip if already mostly English
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    if chinese_chars == 0:
        return text
    
    # Translate in chunks of ~4000 characters to avoid limits
    lines = text.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0
    
    for line in lines:
        line_len = len(line)
        if current_len + line_len > 4000 and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(line)
        current_len += line_len
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    result_chunks = []
    for chunk in chunks:
        if not chunk.strip():
            result_chunks.append(chunk)
            continue
        
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', chunk))
        if chinese_chars == 0:
            result_chunks.append(chunk)
            continue
        
        try:
            translated = translator.translate(chunk)
            result_chunks.append(translated)
            time.sleep(0.1)  # rate limiting
        except Exception as e:
            print(f"  Translation error: {e}, keeping original")
            result_chunks.append(chunk)
    
    return '\n'.join(result_chunks)

def translate_frontmatter(fm_text, translator):
    """Translate frontmatter: only title and description."""
    lines = fm_text.split('\n')
    result = []
    for line in lines:
        if line.startswith('title:'):
            # Extract title value
            match = re.match(r'(title:\s*)"([^"]*)"', line)
            if match:
                prefix = match.group(1)
                title = match.group(2)
                try:
                    translated_title = translator.translate(title)
                    result.append(f'{prefix}"{translated_title}"')
                    time.sleep(0.1)
                except:
                    result.append(line)
            else:
                result.append(line)
        elif line.startswith('description:'):
            match = re.match(r'(description:\s*)"([^"]*)"', line)
            if match:
                prefix = match.group(1)
                desc = match.group(2)
                try:
                    translated_desc = translator.translate(desc)
                    result.append(f'{prefix}"{translated_desc}"')
                    time.sleep(0.1)
                except:
                    result.append(line)
            else:
                result.append(line)
        else:
            result.append(line)
    return '\n'.join(result)

def translate_file(filepath, output_path):
    """Translate a single markdown file."""
    print(f"\nProcessing: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    translator = GoogleTranslator(source='zh-CN', target='en')
    
    # Split frontmatter and body
    fm_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    if not fm_match:
        print("  No frontmatter found!")
        return
    
    fm_text = fm_match.group(1)
    body = content[fm_match.end():]
    
    # Translate frontmatter
    translated_fm = translate_frontmatter(fm_text, translator)
    
    # Split body into segments
    segments = split_content(body)
    
    # Translate text segments
    translated_segments = []
    for seg_type, seg_content in segments:
        if seg_type == 'text':
            translated = translate_text(seg_content, translator)
            translated_segments.append(translated)
        else:
            translated_segments.append(seg_content)
    
    translated_body = ''.join(translated_segments)
    
    # Add footer with original link
    # Extract slug from filepath
    filename = os.path.basename(filepath)
    slug = filename.replace('.md', '')
    dirname = os.path.basename(os.path.dirname(filepath))
    
    # The original URL structure: https://lastdba.com/YYYY/MM/DD/slug/
    # Extract date from filename (first 10 chars: YYYY-MM-DD)
    date_part = filename[:10]
    year, month, day = date_part.split('-')
    original_url = f"https://lastdba.com/{year}/{month}/{day}/{slug}/"
    
    footer = f"\n\n---\n\n> Original article: [{original_url}]({original_url})\n"
    
    # Build final output
    output = f"---\n{translated_fm}\n---\n{translated_body}{footer}"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output)
    
    print(f"  -> {output_path}")
    print(f"  Output size: {len(output)} chars")

def main():
    for filepath in FILES:
        full_path = os.path.join(BASE_DIR, filepath)
        if not os.path.exists(full_path):
            print(f"File not found: {full_path}")
            continue
        
        output_path = full_path.replace('.md', '.en.md')
        
        if os.path.exists(output_path):
            print(f"Skipping {output_path} (already exists)")
            continue
        
        try:
            translate_file(full_path, output_path)
        except Exception as e:
            print(f"ERROR processing {filepath}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()
