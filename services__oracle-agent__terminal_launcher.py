"""Create one portable MT5 installation per account and launch it isolated."""
import os, shutil, subprocess, time, shlex, sys
from pathlib import Path

class TerminalLauncher:
    def __init__(self,install_root,command_prefix=""):
        self.install_root=Path(install_root).resolve()
        self.command_prefix=shlex.split(command_prefix) if isinstance(command_prefix,str) else list(command_prefix or [])
        binary=self.install_root/"terminal64.exe"
        if not binary.is_file():raise FileNotFoundError("MT5_INSTALL_DIR_must_contain_verified_terminal64.exe")
        if sys.platform.startswith("linux") and not self.command_prefix:
            raise RuntimeError("MT5_LAUNCH_COMMAND_required_on_Linux_(for_example_wine)")
        if self.command_prefix and shutil.which(self.command_prefix[0]) is None and not Path(self.command_prefix[0]).is_file():
            raise FileNotFoundError("MT5_LAUNCH_COMMAND_wrapper_not_found")

    def prepare(self,account_workspace):
        workspace=Path(account_workspace).resolve(); instance=workspace/"terminal"
        if not instance.exists():shutil.copytree(self.install_root,instance,symlinks=False)
        binary=instance/"terminal64.exe"
        if not binary.is_file():raise FileNotFoundError("account_terminal_copy_failed")
        return instance

    def build_command(self,profile_dir,config_path):
        root=Path(profile_dir).resolve(); binary=root/"terminal64.exe"; config=Path(config_path).resolve()
        if not binary.is_file():raise FileNotFoundError("isolated_terminal_binary_missing")
        if root not in config.parents:raise ValueError("terminal_config_must_be_inside_account_instance")
        return self.command_prefix+[str(binary),"/portable",f"/config:{config}"]

    def launch(self,profile_dir,config_path):
        root=Path(profile_dir).resolve(); command=self.build_command(root,config_path)
        process=subprocess.Popen(command,cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,close_fds=True,start_new_session=True)
        # MT5 reads the credential-bearing startup config asynchronously. Keep it
        # available briefly, then AccountScheduler removes it in a finally block.
        time.sleep(4)
        if process.poll() is not None:raise RuntimeError("MT5 terminal exited during startup; inspect private terminal logs")
        return process
