import subprocess
import shutil
import logging
import threading
import os
import shlex
from pathlib import Path
from datetime import datetime
from typing import Any
import yaml
from agents import register_agent
from src.module_registration import AgentType, load_prompt_builder


def integrate_agent_config(prompt, agent_config: dict[str, Any]) -> str:
    """
    Integrate agent config into prompt.
    """
    max_iters = agent_config.get("max_iterations")
    if max_iters is not None:
        prompt = prompt.rstrip() + f"\n\nFor this optimization, you must iterate up to {max_iters} versions."
    python_path = agent_config.get("python_path")
    if python_path:
        prompt = prompt.rstrip() + f"\n\nUse this Python interpreter: `{python_path}`."
    return prompt

def write_debug_script(workspace: str, cmd: str, agent: str) -> None:
    """Optionally write the invocation command to a shell script for debugging."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    script_file = f"run_agent_{timestamp}.sh"

    script_lines = [
        "#!/bin/bash",
        f"# Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Workspace: {workspace}",
        f"# Agent: {agent}",
        "",
        f"cd {workspace}",
        cmd,
    ]

    script_file.write_text("\n".join(script_lines) + "\n")
    os.chmod(script_file, 0o755)


@register_agent("cursor")
def launch_agent(eval_config: dict[str, Any], task_config_dir: str, workspace: str) -> str:
    """
    Launch cursor agent with real-time output streaming.

    Args:
        eval_config: Evaluator settings passed from main (includes task metadata like task_type)
        task_config_dir: Path to the task configuration used to build the prompt
        workspace: Workspace directory where the agent will run and read/write files

    Returns:
        str: Combined agent output (stdout plus stderr summary if present)
    """
    AGENT = "cursor-agent"
    # Use stream-json format with partial output for real-time streaming
    OPTIONS = "--force --print --output-format stream-json --stream-partial-output"
    
    config_path = Path(__file__).with_name("agent_config.yaml")
    with config_path.open("r") as f:
        agent_config = yaml.safe_load(f) or {}
    logger = logging.getLogger(__name__)

    # Check if the command exists
    if not shutil.which(AGENT):
        raise RuntimeError(
            f"Command '{AGENT}' not found. Please ensure cursor-agent is installed and in your PATH."
        )
    
    prompt_builder = load_prompt_builder(AgentType.CURSOR, logger)
    prompt = prompt_builder(task_config_dir, workspace, eval_config, logger)

    prompt = integrate_agent_config(prompt, agent_config)
    quoted_prompt = shlex.quote(prompt)
    cmd = f"{AGENT} {OPTIONS} {quoted_prompt}"

    # Enable to save the command to a shell script for manual replay/debugging.
    if False:
        write_debug_script(workspace, cmd, AGENT)
        logger.info("Debug script written; skipping live run.")
        return ""
    
    agent_log_path = Path(workspace) / "agent_output.log"
    logger.info(f"Agent output log: {agent_log_path}")
    logger.info(f"Running command: {cmd}")
    logger.info("=" * 80)
    logger.info("Agent Output (streaming):")
    logger.info("=" * 80)

    # Give the agent a hard stop to avoid blocking downstream tasks if it
    # keeps waiting for interactive input after finishing its work.
    timeout_seconds = int(agent_config.get("timeout_seconds", 300))

    # Use Popen for real-time output streaming with interactive input support
    process = subprocess.Popen(
        cmd,
        shell=True,  # nosec B602 -- shell=True is required to launch agent process
        stdin=subprocess.PIPE,  # Keep stdin closed so the agent exits when done
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=workspace,
        bufsize=1  # Line buffered
    )

    # Close stdin immediately; leaving it attached keeps the agent alive waiting
    # for more user messages even after it reports completion.
    if process.stdin:
        process.stdin.close()

    # Collect output while streaming
    stdout_lines = []
    stderr_lines = []
    log_lock = threading.Lock()
    agent_log_file = agent_log_path.open("a", encoding="utf-8")

    def write_agent_log(line: str) -> None:
        with log_lock:
            agent_log_file.write(line + "\n")
            agent_log_file.flush()

    def format_agent_event(data):
        """Convert cursor stream-json payloads into a readable single-line string."""
        if not isinstance(data, dict):
            return str(data)

        event_type = data.get("type")
        if event_type == "assistant":
            content = data.get("message", {}).get("content", [])
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
            text = " ".join(t.strip() for t in texts if t and t.strip())
            return f"assistant: {text}" if text else "assistant (no text)"

        if event_type == "thinking":
            text = " ".join((data.get("text") or "").split())
            subtype = data.get("subtype")
            # Skip empty deltas to avoid noisy blank lines
            if not text:
                return None
            return f"thinking[{subtype}] {text}" if subtype else f"thinking {text}"

        if event_type == "tool_call":
            subtype = data.get("subtype")
            call = data.get("tool_call") or {}
            call_name = next(iter(call.keys()), "unknown_tool")
            args = call.get(call_name, {}).get("args", {}) if isinstance(call, dict) else {}
            summary = []
            if isinstance(args, dict):
                if "path" in args:
                    summary.append(f"path={args.get('path')}")
                if "command" in args:
                    summary.append(f"cmd={args.get('command')}")
            details = " ".join(summary)
            result_str = f"tool_call[{subtype}] {call_name} {details}".strip()
            
            # Check if result is included in the tool_call event (especially for completed calls)
            if subtype == "completed":
                result = data.get("result") or call.get(call_name, {}).get("result") or data.get("tool_result")
                if result is not None:
                    # Format the result
                    if isinstance(result, dict):
                        content = result.get("content", result.get("text", result.get("output", "")))
                        if isinstance(content, str) and content:
                            if len(content) > 1000:
                                content = content[:1000] + "... [truncated]"
                            result_str += f"\n  result: {content}"
                        elif isinstance(content, list):
                            texts = []
                            for part in content:
                                if isinstance(part, dict):
                                    if part.get("type") == "text":
                                        texts.append(part.get("text", ""))
                                    elif part.get("type") == "error":
                                        texts.append(f"[ERROR] {part.get('error', '')}")
                                elif isinstance(part, str):
                                    texts.append(part)
                            if texts:
                                combined = " ".join(t.strip() for t in texts if t.strip())
                                if len(combined) > 1000:
                                    combined = combined[:1000] + "... [truncated]"
                                result_str += f"\n  result: {combined}"
                    elif isinstance(result, str):
                        if len(result) > 1000:
                            result = result[:1000] + "... [truncated]"
                        result_str += f"\n  result: {result}"
            
            return result_str

        if event_type in ("tool_result", "tool_observation", "tool_call_result"):
            # Handle tool result/observation events
            result = data.get("tool_result") or data.get("tool_observation") or data.get("result") or {}
            if isinstance(result, dict):
                # Try to extract meaningful information
                content = result.get("content", "")
                if isinstance(content, str):
                    # Truncate long outputs for readability
                    if len(content) > 500:
                        content = content[:500] + "... [truncated]"
                    return f"tool_observation: {content}"
                elif isinstance(content, list):
                    # Handle structured content
                    texts = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                texts.append(part.get("text", ""))
                            elif part.get("type") == "error":
                                texts.append(f"[ERROR] {part.get('error', '')}")
                    if texts:
                        combined = " ".join(t.strip() for t in texts if t.strip())
                        if len(combined) > 500:
                            combined = combined[:500] + "... [truncated]"
                        return f"tool_observation: {combined}"
            # Fallback: show raw result if it's a simple type
            if isinstance(result, (str, int, float, bool)):
                result_str = str(result)
                if len(result_str) > 500:
                    result_str = result_str[:500] + "... [truncated]"
                return f"tool_observation: {result_str}"
            # If result is complex, show a summary
            return f"tool_observation: [result received]"

        if event_type == "user":
            message = data.get("message", {}).get("content", [])
            texts = []
            for part in message:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
            text = " ".join(t.strip() for t in texts if t and t.strip())
            if not text:
                return "user (no text)"
            text = " ".join(text.split())
            return f"user: {text}"

        if event_type == "system":
            model = data.get("model")
            cwd = data.get("cwd")
            return f"system init model={model} cwd={cwd}"

        # Fallback: compact json - log unknown event types for debugging
        import json
        # Only log if it's not an empty dict or known to be noisy
        if data and event_type not in ("ping", "pong", "heartbeat"):
            json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            # Truncate very long JSON
            if len(json_str) > 2000:
                json_str = json_str[:2000] + "... [truncated]"
            return f"[UNKNOWN_EVENT type={event_type}] {json_str}"
        return None

    def read_stream(stream, output_list, prefix, log_func):
        """Read from stream in a separate thread to avoid blocking"""
        import json
        import ast
        assistant_buffer: list[str] = []
        thinking_buffer: list[str] = []
        thinking_subtype: str = None

        def flush_assistant_buffer() -> None:
            if not assistant_buffer:
                return
            combined = " ".join(part for part in assistant_buffer if part)
            assistant_buffer.clear()
            if combined.strip():
                formatted = f"assistant: {combined.strip()}"
                output_list.append(formatted)
                log_line = f"{prefix} {formatted}"
                log_func(log_line)
                write_agent_log(log_line)

        def flush_thinking_buffer() -> None:
            nonlocal thinking_subtype
            if not thinking_buffer:
                return
            combined = " ".join(part for part in thinking_buffer if part)
            thinking_buffer.clear()
            if combined.strip():
                subtype_str = f"[{thinking_subtype}]" if thinking_subtype else ""
                formatted = f"thinking{subtype_str} {combined.strip()}"
                output_list.append(formatted)
                log_line = f"{prefix} {formatted}"
                log_func(log_line)
                write_agent_log(log_line)
            thinking_subtype = None

        try:
            for line in iter(stream.readline, ''):
                if not line:
                    break
                raw_line = line.rstrip()

                # Try to parse as JSON (stream-json format)
                try:
                    data = json.loads(raw_line)
                    event_type = data.get("type") if isinstance(data, dict) else None
                    if event_type == "assistant":
                        flush_thinking_buffer()
                        content = data.get("message", {}).get("content", [])
                        texts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                texts.append(part.get("text", ""))
                        text = " ".join(t.strip() for t in texts if t and t.strip())
                        if text:
                            assistant_buffer.append(text)
                        continue

                    if event_type == "thinking":
                        subtype = data.get("subtype")
                        text = " ".join((data.get("text") or "").split())
                        if text:
                            # If subtype changed, flush previous buffer
                            if thinking_subtype is not None and thinking_subtype != subtype:
                                flush_thinking_buffer()
                            thinking_subtype = subtype
                            thinking_buffer.append(text)
                        continue

                    flush_assistant_buffer()
                    flush_thinking_buffer()
                    formatted = format_agent_event(data)
                    if formatted:
                        # Handle multi-line output (e.g., tool results with newlines)
                        lines = formatted.split('\n')
                        for i, line in enumerate(lines):
                            if i == 0:
                                output_list.append(line)
                                log_line = f"{prefix} {line}"
                            else:
                                # Indent continuation lines
                                output_list.append(line)
                                log_line = f"{prefix}   {line}"
                            log_func(log_line)
                            write_agent_log(log_line)
                    continue
                except json.JSONDecodeError:
                    try:
                        data = ast.literal_eval(raw_line)
                        event_type = data.get("type") if isinstance(data, dict) else None
                        if event_type == "assistant":
                            flush_thinking_buffer()
                            content = data.get("message", {}).get("content", [])
                            texts = []
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    texts.append(part.get("text", ""))
                            text = " ".join(t.strip() for t in texts if t and t.strip())
                            if text:
                                assistant_buffer.append(text)
                            continue

                        if event_type == "thinking":
                            subtype = data.get("subtype")
                            text = " ".join((data.get("text") or "").split())
                            if text:
                                # If subtype changed, flush previous buffer
                                if thinking_subtype is not None and thinking_subtype != subtype:
                                    flush_thinking_buffer()
                                thinking_subtype = subtype
                                thinking_buffer.append(text)
                            continue

                        flush_assistant_buffer()
                        flush_thinking_buffer()
                        formatted = format_agent_event(data)
                        if formatted:
                            # Handle multi-line output (e.g., tool results with newlines)
                            lines = formatted.split('\n')
                            for i, line in enumerate(lines):
                                if i == 0:
                                    output_list.append(line)
                                    log_line = f"{prefix} {line}"
                                else:
                                    # Indent continuation lines
                                    output_list.append(line)
                                    log_line = f"{prefix}   {line}"
                                log_func(log_line)
                                write_agent_log(log_line)
                        continue
                    except Exception:
                        pass

                flush_assistant_buffer()
                flush_thinking_buffer()
                if raw_line.strip():
                    output_list.append(raw_line)
                    log_line = f"{prefix} {raw_line}"
                    log_func(log_line)
                    write_agent_log(log_line)
        finally:
            flush_assistant_buffer()
            flush_thinking_buffer()
            stream.close()

    # Create threads to read stdout and stderr concurrently
    # This allows user interaction to work while we capture output
    stdout_thread = threading.Thread(
        target=read_stream,
        args=(process.stdout, stdout_lines, "[AGENT]", logger.info),
        daemon=True
    )
    stderr_thread = threading.Thread(
        target=read_stream,
        args=(process.stderr, stderr_lines, "[AGENT STDERR]", logger.warning),
        daemon=True
    )

    # Start reading threads
    stdout_thread.start()
    stderr_thread.start()

    # Wait for process to complete
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.warning(f"Cursor agent timed out after {timeout_seconds}s; terminating process")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Force killing cursor agent process")
            process.kill()

    # Wait for output threads to finish reading
    stdout_thread.join()
    stderr_thread.join()
    agent_log_file.close()

    # Log stderr summary if present
    if stderr_lines:
        logger.warning("=" * 80)
        logger.warning(f"Agent STDERR captured {len(stderr_lines)} lines")
        logger.warning("=" * 80)

    logger.info("=" * 80)
    logger.info(f"Agent completed with exit code: {process.returncode}")
    logger.info("=" * 80)

    # Return combined output
    output = "\n".join(stdout_lines)
    if stderr_lines:
        output += "\n=== STDERR ===\n" + "\n".join(stderr_lines)

    return output
