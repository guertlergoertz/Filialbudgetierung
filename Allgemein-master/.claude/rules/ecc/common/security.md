# Security Guidelines

## General Principles
- Never store secrets in code
- Use environment variables for configuration
- Validate all inputs
- Apply principle of least privilege

## Authentication & Authorization
- Use established libraries, don't roll your own
- Implement proper session management
- Use HTTPS everywhere
- Implement rate limiting

## Data Security
- Encrypt sensitive data at rest
- Use parameterized queries to prevent SQL injection
- Sanitize outputs to prevent XSS
- Implement proper CORS policies

## Dependency Management
- Regularly update dependencies
- Scan for known vulnerabilities
- Pin dependency versions
- Review security advisories
