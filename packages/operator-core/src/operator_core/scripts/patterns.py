"""Pattern definitions for script security scanning.

This module defines regex patterns for detecting secrets and dangerous
code patterns in Python and Bash scripts. Used by ScriptValidator to
prevent execution of potentially unsafe scripts.
"""

# Secret patterns (VALD-03)
# Detects hardcoded credentials and sensitive data in script content
SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key)\s*[=:]\s*['\"][^'\"]+['\"]", "API key assignment"),
    (r"(?i)(password)\s*[=:]\s*['\"][^'\"]+['\"]", "password assignment"),
    (r"(?i)(token)\s*[=:]\s*['\"][^'\"]+['\"]", "token assignment"),
    (r"(?i)(secret)\s*[=:]\s*['\"][^'\"]+['\"]", "secret assignment"),
    (r"(?i)(aws_access_key_id)\s*[=:]\s*['\"][A-Z0-9]{20}['\"]", "AWS access key"),
    (r"(?i)(aws_secret_access_key)\s*[=:]\s*", "AWS secret key"),
    (r"-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
]

# Python dangerous patterns (VALD-04)
# Detects code execution and introspection patterns that break sandbox isolation
PYTHON_DANGEROUS_PATTERNS = [
    (r"\beval\s*\(", "eval() function"),
    (r"\bexec\s*\(", "exec() function"),
    (r"\b__import__\s*\(", "__import__() function"),
    (r"\bos\.system\s*\(", "os.system() call"),
    (r"\bsubprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*True", "subprocess with shell=True"),
    (r"\bcompile\s*\(", "compile() function"),
    (r"\bgetattr\s*\(.*['\"]__", "getattr with dunder access"),
]

# Bash dangerous patterns (VALD-04)
# Detects shell patterns that enable arbitrary code execution
BASH_DANGEROUS_PATTERNS = [
    (r"\beval\s+", "eval command"),
    (r"\$\(\s*\$", "nested command substitution"),
    (r"\bcurl\s+.*\|\s*(bash|sh)", "curl piped to shell"),
    (r"\bwget\s+.*\|\s*(bash|sh)", "wget piped to shell"),
]
