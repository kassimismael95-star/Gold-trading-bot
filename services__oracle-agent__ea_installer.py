"""Deploy EA source/expert only to the account's isolated terminal data directory."""
import shutil
from pathlib import Path
def install_ea(source_expert_dir,terminal_data_dir,ea_name="GoldScalper"):
 src=Path(source_expert_dir).resolve(); dst=(Path(terminal_data_dir)/"MQL5"/"Experts"/ea_name).resolve()
 if not src.is_dir(): raise FileNotFoundError(src)
 dst.mkdir(parents=True,exist_ok=True)
 for f in src.iterdir():
  if f.is_file() and f.suffix.lower() in {".mq5",".mqh",".ex5"}: shutil.copy2(f,dst/f.name)
 return str(dst)
