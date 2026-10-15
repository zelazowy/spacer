"""Small portable UI preferences; never required to open or render a project."""
import json
from pathlib import Path

DEFAULT_PATH=Path(__file__).resolve().parents[1]/'.spacer-settings.json'


class Preferences:
    def __init__(self,path=None):
        self.path=Path(path) if path is not None else DEFAULT_PATH
        try:
            value=json.loads(self.path.read_text())
            self.data=value if isinstance(value,dict) else {}
        except (OSError,ValueError): self.data={}

    def save(self,**changes):
        self.data.update(changes)
        temporary=self.path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(self.data,indent=2))
            temporary.replace(self.path)
            return True
        except OSError: return False

    def directory(self,key):
        value=self.data.get(key,'')
        if isinstance(value,str) and value and Path(value).is_dir(): return value
        return str(Path.home())
