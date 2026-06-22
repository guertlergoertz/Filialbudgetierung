# Security Guidelines

## Never Do

- Hardcode credentials, tokens, API keys
- Log sensitive data (passwords, PII)
- Use `eval()` or `exec()` on user input
- Build SQL with string concatenation
- Trust user input without validation

## Always Do

### Credentials
```python
import os
API_KEY = os.environ["API_KEY"]  # from environment
```

### SQL
```python
# Bad
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# Good
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### File Paths
```python
import os
safe_path = os.path.realpath(user_path)
if not safe_path.startswith(ALLOWED_DIR):
    raise ValueError("Path traversal detected")
```

## Sensitive Files

Never commit:
- `.env` files
- `*.key`, `*.pem` files
- Database files with real data
- Config files with passwords

Always in `.gitignore`:
```
.env
*.key
*.pem
data/*.db
```
