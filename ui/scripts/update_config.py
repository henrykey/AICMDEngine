import yaml
import json
import sys
import os

def convert():
    try:
        # Assuming run from ui/ directory
        config_path = os.path.join(os.getcwd(), '../../config.yml')
        # Fallback if run from root
        if not os.path.exists(config_path):
             config_path = 'config.yml'

        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            frontend_config = data.get('frontend', {})
            
        if os.path.exists('ui/public'):
            out_path = 'ui/public/config.json'
        elif os.path.exists('public'):
             out_path = 'public/config.json'
        else:
             print("Could not find public dir")
             sys.exit(1)

        with open(out_path, 'w') as f:
            json.dump(frontend_config, f, indent=2)
            
        print("Successfully generated public/config.json from config.yml")
    except Exception as e:
        print(f"Error converting config: {e}")
        sys.exit(1)

if __name__ == "__main__":
    convert()
