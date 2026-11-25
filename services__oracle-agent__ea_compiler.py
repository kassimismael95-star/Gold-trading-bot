"""MetaEditor compiler adapter; supports a command wrapper such as `wine`."""
import os, shlex, subprocess

def compile_ea(metaeditor,source,log_path,timeout=180):
    command=shlex.split(metaeditor) if isinstance(metaeditor,str) else list(metaeditor)
    if not command: raise ValueError("METAEDITOR_COMMAND_required")
    executable=command[0]
    if os.path.sep in executable and not os.path.isfile(executable):
        raise FileNotFoundError("MetaEditor_or_wrapper_not_found")
    result=subprocess.run(command+[f"/compile:{os.path.abspath(source)}",f"/log:{os.path.abspath(log_path)}"],
                          timeout=timeout,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {"returncode":result.returncode,"log_path":os.path.abspath(log_path),"success":result.returncode==0}
