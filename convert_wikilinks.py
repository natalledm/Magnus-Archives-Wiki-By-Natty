#!/usr/bin/env python3
"""
convert_wikilinks.py

Converts Obsidian-style [[Wikilinks]] into standard relative Markdown links
so they render correctly on GitHub.

WHAT IT HANDLES:
    [[Page Name]]                        -> [Page Name](relative/path/Page%20Name.md)
    [[Page Name|Display Text]]           -> [Display Text](relative/path/Page%20Name.md)
    [[Page Name#Heading]]                -> [Page Name > Heading](relative/path/Page%20Name.md#heading)
    [[Page Name#Heading|Display Text]]   -> [Display Text](relative/path/Page%20Name.md#heading)
    ![[Image.png]]                       -> ![Image.png](relative/path/Image.png)   (embeds/images)

NOTES:
    - Link resolution is name-based: it scans every file in the repo (.md, images,
      etc.) and matches on filename regardless of which folder it's actually in,
      exactly like Obsidian does. This means it correctly finds e.g. "Jonah Magnus"
      even though the link doesn't mention the "People" folder.
    - If a linked page/file can't be found anywhere in the repo, the script leaves
      a plain-text fallback (no broken link) and prints a warning so you can check
      it manually (this usually means a typo, or a note that hasn't been created yet).
    - Heading anchors are lowercased and spaces turned into hyphens to match
      GitHub's auto-generated heading anchor format.
"""

import os
import re
import sys
import urllib.parse

# File extensions Obsidian wikilinks can point to (notes + common embed types)
LINKABLE_EXTS = ['.md', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.pdf', '.webp']

# Folders to skip when indexing / walking
SKIP_DIRS = {'.git', '.obsidian'}

WIKILINK_RE = re.compile(
    r'(!?)\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]'
)


def build_file_index(root):
    """Map lowercased filename (without extension, and with extension) -> relative path."""
    index_by_stem = {}
    index_by_full = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in LINKABLE_EXTS:
                continue
            full_path = os.path.relpath(os.path.join(dirpath, fname), root)
            stem = os.path.splitext(fname)[0]
            key_stem = stem.lower()
            key_full = fname.lower()
            # Prefer first match if duplicate names exist across folders;
            # warn later if that becomes ambiguous.
            index_by_stem.setdefault(key_stem, []).append(full_path)
            index_by_full.setdefault(key_full, []).append(full_path)
    return index_by_stem, index_by_full


def slugify_heading(heading):
    """Approximate GitHub's heading-anchor slug algorithm."""
    slug = heading.strip().lower()
    slug = re.sub(r'[^\w\s-]', '', slug)  # strip punctuation
    slug = re.sub(r'\s+', '-', slug)
    return slug


def resolve_target(link_target, index_by_stem, index_by_full, current_file_dir, root, warnings, link_target_raw):
    """Return a relative (URL-encoded) path from the current file to the link target, or None."""
    # link_target may or may not include an extension
    stem, ext = os.path.splitext(link_target)
    candidates = []

    if ext.lower() in LINKABLE_EXTS:
        candidates = index_by_full.get(link_target.lower(), [])
    else:
        # No extension given -> assume it's a note (.md) first, but also check
        # other extensions in case it's an image/pdf referenced without extension.
        candidates = index_by_stem.get(link_target.lower(), [])

    if not candidates:
        warnings.append(f'  - Could not resolve link target: "{link_target_raw}"')
        return None

    if len(candidates) > 1:
        warnings.append(
            f'  - Multiple files named "{link_target}" found ({candidates}); using the first one.'
        )

    target_abs = os.path.join(root, candidates[0])
    rel = os.path.relpath(target_abs, current_file_dir)
    rel = rel.replace(os.sep, '/')
    # URL-encode spaces and special characters but keep the path structure
    rel_encoded = '/'.join(urllib.parse.quote(part) for part in rel.split('/'))
    return rel_encoded


def convert_file(filepath, index_by_stem, index_by_full, root, warnings):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    current_dir = os.path.dirname(filepath)

    def replacer(match):
        is_embed, target, heading, display = match.groups()
        target = target.strip()
        display_text = display.strip() if display else target
        if heading:
            heading = heading.strip()
            display_text = display.strip() if display else f'{target} > {heading}'

        rel_link = resolve_target(
            target, index_by_stem, index_by_full, current_dir, root, warnings, match.group(0)
        )

        if rel_link is None:
            # Leave a plain, non-broken-link fallback
            return display_text

        anchor = f'#{slugify_heading(heading)}' if heading else ''
        prefix = '!' if is_embed else ''
        return f'{prefix}[{display_text}]({rel_link}{anchor})'

    new_content = WIKILINK_RE.sub(replacer, content)
    return new_content, new_content != content


def main():
    root = os.getcwd()
    dry_run = '--dry-run' in sys.argv

    print(f'Scanning repository at: {root}')
    index_by_stem, index_by_full = build_file_index(root)

    md_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname.lower().endswith('.md'):
                md_files.append(os.path.join(dirpath, fname))

    print(f'Found {len(md_files)} markdown files.\n')

    total_changed = 0
    all_warnings = []

    for filepath in md_files:
        warnings = []
        new_content, changed = convert_file(filepath, index_by_stem, index_by_full, root, warnings)
        rel_path = os.path.relpath(filepath, root)

        if warnings:
            print(f'{rel_path}:')
            for w in warnings:
                print(w)
            all_warnings.extend(warnings)

        if changed:
            total_changed += 1
            if dry_run:
                print(f'[DRY RUN] Would update: {rel_path}')
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f'Updated: {rel_path}')

    print(f'\nDone. {total_changed} file(s) {"would be" if dry_run else ""} updated.')
    if all_warnings:
        print(f'{len(all_warnings)} warning(s) above — review unresolved links manually.')


if __name__ == '__main__':
    main()
