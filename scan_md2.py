"""Comprehensive MarkdownV2 scanner — finds ALL unescaped reserved characters."""
import re, os, sys
sys.stdout.reconfigure(encoding='utf-8')

# MarkdownV2 reserved chars that MUST be escaped with \ 
RESERVED = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

files = []
for root, dirs, fnames in os.walk('bot'):
    for f in fnames:
        if f.endswith('.py'):
            files.append(os.path.join(root, f))

issues = []

for fpath in files:
    with open(fpath, 'r', encoding='utf-8') as fh:
        lines = fh.readlines()

    # Find all MarkdownV2 blocks
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if 'parse_mode="MarkdownV2"' not in stripped:
            continue
        
        # Check 30 lines above for f-strings that are part of the text
        for j in range(max(0, i-30), i):
            prev = lines[j].strip()
            # Only f-strings
            if not (prev.startswith('f"') or prev.startswith("f'")):
                continue
            # Skip non-message content
            if 'callback_data' in prev or 'logger' in prev:
                continue
            if prev.startswith('text=f"') or prev.startswith("text=f'"):
                continue
            
            # Check for literal = not escaped
            # Find = that isn't inside {} and isn't preceded by \
            for match in re.finditer(r'(?<!\\)=', prev):
                pos = match.start()
                # Skip if inside {escape_md(...)} 
                before = prev[:pos]
                if before.count('{') > before.count('}'):
                    continue  # Inside an f-string expression
                fname = os.path.basename(fpath)
                issues.append(f"UNESCAPED =  -> {fname}:{j+1}: {prev[:80]}")

            # Check for literal & not escaped  
            for match in re.finditer(r'(?<!\\)&', prev):
                pos = match.start()
                before = prev[:pos]
                if before.count('{') > before.count('}'):
                    continue
                fname = os.path.basename(fpath)
                issues.append(f"UNESCAPED &  -> {fname}:{j+1}: {prev[:80]}")

            # Check for literal | not inside escape
            for match in re.finditer(r'(?<!\\)\|', prev):
                pos = match.start()
                before = prev[:pos]
                if before.count('{') > before.count('}'):
                    continue
                fname = os.path.basename(fpath)
                issues.append(f"UNESCAPED |  -> {fname}:{j+1}: {prev[:80]}")

for issue in issues:
    print(issue)

print(f"\nTotal issues: {len(issues)}")
print("SCAN COMPLETE")
