"""Check Git-tracked release files without printing credential values."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
files = [name for name in files if name]
errors = []
secrets = set()
secret_keys = {'ARK_API_KEY', 'VOLC_ACCESS_KEY', 'VOLC_SECRET_KEY', 'RTC_APP_KEY', 'CALLBACK_API_KEY'}
for env in (ROOT / 'rag_llm_server/.env', ROOT / 'server_python/.env'):
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            value = value.strip().strip('\"\'')
            if sep and key.strip() in secret_keys and len(value) >= 12:
                secrets.add(value)

def collect(value, key=''):
    if isinstance(value, dict):
        for name, child in value.items():
            collect(child, name)
    elif isinstance(value, list):
        for child in value:
            collect(child, key)
    elif isinstance(value, str) and re.search(r'key|token|secret', key, re.I) and len(value) >= 12:
        if not any(word in value.lower() for word in ('your', 'example', 'placeholder', '填', '<')):
            secrets.add(value)

for config in (ROOT / 'rag_llm_server/voice_config.json', ROOT / 'Server/scenes/Custom.json'):
    if config.exists():
        collect(json.loads(config.read_text(encoding='utf-8-sig')))

for name in files:
    path = ROOT / name
    parts = Path(name).parts
    if any(part in {'.runtime', 'node_modules', '.venv', '__pycache__', 'build'} for part in parts):
        errors.append(f'Forbidden artifact: {name}')
    if path.name.startswith('.env') and path.name not in {'.env.example', '.env.sample'}:
        errors.append(f'Local environment file: {name}')
    if path.name == 'voice_config.json':
        errors.append(f'Local voice configuration: {name}')
    raw = path.read_bytes()
    if len(raw) > 95 * 1024 * 1024:
        errors.append(f'File too large: {name}')
    if any(secret.encode() in raw for secret in secrets):
        errors.append(f'Local credential detected: {name}')

for name in ['README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'docs/DOCUMENTATION.md',
             'docs/DEPLOYMENT.md', 'docs/PUBLISHING.md']:
    path = ROOT / name
    text = path.read_text(encoding='utf-8-sig')
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if re.match(r'https?://|#', target):
            continue
        local = target.split('#', 1)[0]
        if local and not (path.parent / local).exists():
            errors.append(f'Broken local link in {name}: {local}')

for error in errors:
    print(error)
if errors:
    raise SystemExit(1)
print(f'Release checks passed: {len(files)} tracked files; local credential values absent; links valid.')
