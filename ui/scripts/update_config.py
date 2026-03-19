import yaml
import json
import sys
import os


def load_dotenv_file(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            # strip inline comments
            value = value.split('#')[0].strip()
            env[key.strip()] = value
    return env


def convert():
    # Locate config.yml
    config_path = os.path.join(os.getcwd(), '../../config.yml')
    if not os.path.exists(config_path):
        config_path = 'config.yml'
    if not os.path.exists(config_path):
        print("Error: config.yml not found")
        sys.exit(1)

    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    # Load .env from project root (same dir as config.yml)
    env_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), '.env')
    env = load_dotenv_file(env_path)

    # Priority: CMD_ENGINE_URL in .env > backend section in config.yml > error
    cmd_engine_url = env.get('CMD_ENGINE_URL', '').strip()
    if cmd_engine_url:
        nl_tps_api_url = cmd_engine_url
    else:
        backend = data.get('backend') or {}
        host = backend.get('host')
        port = backend.get('port')
        base_path = backend.get('base_path') or ''
        if not host or not port:
            print("Error: CMD_ENGINE_URL not set in .env and backend.host/port missing in config.yml")
            sys.exit(1)
        nl_tps_api_url = f"http://{host}:{port}{base_path}"

    frontend = data.get('frontend') or {}
    membership = frontend.get('membership') or {}
    config = {
        'nlTpsApiUrl': nl_tps_api_url,
        'membershipApiUrl': frontend.get('membership_api_url', 'http://localhost:8080'),
        'membershipLoginPath': membership.get('login_path', '/v2/auth/login'),
        'membershipUserPath': membership.get('user_path', '/v2/users/me'),
    }

    # Write to all known public dirs that exist
    candidates = ['ui/public', 'plan2/public', 'public']
    written = []
    for d in candidates:
        if os.path.exists(d):
            out_path = os.path.join(d, 'config.json')
            with open(out_path, 'w') as f:
                json.dump(config, f, indent=2)
                f.write('\n')
            written.append(out_path)

    if not written:
        print("Error: could not find any public dir (ui/public, plan2/public, public)")
        sys.exit(1)

    print(f"Generated config.json -> nlTpsApiUrl={nl_tps_api_url}")
    for p in written:
        print(f"  wrote: {p}")


if __name__ == "__main__":
    convert()
