import os


def load_env_file(path: str):
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if k and os.environ.get(k) in (None, ""):
                    os.environ[k] = v
    except Exception:
        pass


def bootstrap_env(base_dir: str):
    load_env_file(os.path.join(base_dir, ".env.local"))
    load_env_file(os.path.join(base_dir, ".env"))

