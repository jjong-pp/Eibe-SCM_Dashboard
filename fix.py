import re

with open('C:/Users/parkj/.gemini/antigravity/worktrees/SCM-dashboad/refactor-add-error-handling/web/matching.html', 'rb') as f:
    content = f.read()

# Fix <title> tag
content = re.sub(b'<title>(.*?)/title>', b'<title>\g<1></title>', content)

# Fix missing quote in title attribute
# title="?이?바 ?기/?치?> should be title="?이?바 ?기/?치?">
content = re.sub(b'title=\"([^\"]*?)>\r\n', b'title=\"\g<1>\">\r\n', content)
content = re.sub(b'title=\"([^\"]*?)>\n', b'title=\"\g<1>\">\n', content)

with open('C:/Users/parkj/.gemini/antigravity/worktrees/SCM-dashboad/refactor-add-error-handling/web/matching.html', 'wb') as f:
    f.write(content)

print('Fixed matching.html')
