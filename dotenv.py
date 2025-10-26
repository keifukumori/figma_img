import os

def load_dotenv(path: str = None, *args, **kwargs):
    # Minimal loader: read .env in CWD if present
    env_path = path or '.env'
    if not os.path.exists(env_path):
        # try repo root
        env_path = os.path.join(os.getcwd(), '.env')
        if not os.path.exists(env_path):
            return False
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                if '=' in s:
                    k, v = s.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())
        return True
    except Exception:
        return False

