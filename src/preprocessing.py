# This script will setup environment tools and dependencies. It will also provide duplicated workspace for the agent
import os
import shutil
import logging
import subprocess
from pathlib import Path


def check_environment() -> None:
    # check hipcc, rocprof-compute
    if "hipcc" not in os.environ["PATH"]:
        raise ValueError("hipcc is not in the PATH")
    if "rocprof-compute" not in os.environ["PATH"]:
        raise ValueError("rocprof-compute is not in the PATH")
    pass


def setup_workspace(task_config_dir: str, workspace_directory: str, timestamp: str, logger: logging.Logger) -> Path:
    """
    Setup workspace for agent execution by duplicating task directory.

    Args:
        task_config_dir: Path to task's config.yaml
        workspace_directory: Base workspace directory
        timestamp: Timestamp string for unique workspace naming
        logger: Logger instance

    Returns:
        Path to the created workspace directory
    """
    # 1. Get task_folder name (parent directory of task_config_dir)
    task_config_path = Path(task_config_dir)
    task_folder = task_config_path.parent
    task_folder_name = task_folder.name

    # 2. Create new directory with timestamp suffix under workspace_dir
    new_folder_name = f"{task_folder_name}_{timestamp}"
    workspace_path = Path(workspace_directory) / new_folder_name
    workspace_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Created workspace directory: {workspace_path}")

    # 3. Duplicate all content under task_folder to the new workspace folder
    for item in task_folder.iterdir():
        src = item
        dst = workspace_path / item.name
        if item.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    logger.info(f"Copied task folder content from {task_folder} to {workspace_path}")

    # 4. Setup task-specific dependencies
    _setup_task_dependencies(task_folder_name, workspace_path, task_config_path, logger)

    return workspace_path


def _setup_task_dependencies(task_name: str, workspace_path: Path, task_config_path: Path, logger: logging.Logger) -> None:
    """
    Setup task-specific dependencies (e.g., rocPRIM, tritonbench).
    
    Args:
        task_name: Name of the task (e.g., "device_segmented_reduce")
        workspace_path: Path to the workspace directory
        task_config_path: Path to the task config.yaml
        logger: Logger instance
    """
    task_name_lower = task_name.lower()
    # Also check parent directory path (e.g., "rocprim/device_segmented_reduce")
    task_path_str = str(task_config_path.parent).lower()
    
    # Setup rocPRIM for rocprim tasks
    if "rocprim" in task_name_lower or "rocprim" in task_path_str:
        rocprim_path = workspace_path / "rocPRIM"
        if not rocprim_path.exists():
            logger.info(f"Cloning rocPRIM to {rocprim_path}")
            try:
                subprocess.run(
                    ["git", "clone", "https://github.com/ROCm/rocPRIM.git", str(rocprim_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info("rocPRIM cloned successfully")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to clone rocPRIM: {e.stderr}")
                logger.warning("Agent may need to manually copy rocPRIM")
        
        # Copy test_correctness_benchmark.py if it exists in task folder
        test_script_src = task_config_path.parent / "python_bindings" / "test_correctness_benchmark.py"
        test_script_dst = workspace_path / "python_bindings" / "test_correctness_benchmark.py"
        if test_script_src.exists():
            test_script_dst.parent.mkdir(parents=True, exist_ok=True)
            if not test_script_dst.exists():
                shutil.copy(test_script_src, test_script_dst)
                logger.info(f"Copied test_correctness_benchmark.py to {test_script_dst}")
    
    # Setup tritonbench for triton tasks
    if ("triton" in task_name_lower and "tritonbench" in task_name_lower) or "triton/tritonbench" in task_path_str:
        tritonbench_script_src = task_config_path.parent / "python_bindings" / "tritonbench.py"
        tritonbench_script_dst = workspace_path / "python_bindings" / "tritonbench.py"
        if tritonbench_script_src.exists():
            tritonbench_script_dst.parent.mkdir(parents=True, exist_ok=True)
            if not tritonbench_script_dst.exists():
                shutil.copy(tritonbench_script_src, tritonbench_script_dst)
                logger.info(f"Copied tritonbench.py to {tritonbench_script_dst}")
