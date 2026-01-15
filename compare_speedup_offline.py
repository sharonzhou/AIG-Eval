#!/usr/bin/env python3
import csv
import re
import sys
from pathlib import Path


def parse_log(path: Path):
    """Parse rocPRIM benchmark output, return list of bytes_per_second (converted to G/s) in order"""
    results = []

    # Support G/s + T/s
    pattern = re.compile(
        r"^(?P<name>.+?)/manual_time.*?bytes_per_second=(?P<bps>[\d\.]+)(?P<unit>[GT])/s",
        re.MULTILINE,
    )

    try:
        text = path.read_text(encoding="utf8")
    except Exception as e:
        print(f"❌ Error reading file: {path} ({e})")
        return results

    for m in pattern.finditer(text):
        bps = float(m.group("bps"))
        unit = m.group("unit")

        # Convert T/s → G/s
        if unit == "T":
            bps *= 1024.0

        results.append(bps)

    return results


def parse_baseline(path: Path):
    """Parse baseline file, return list of bandwidth values (G/s)"""
    try:
        lines = path.read_text(encoding="utf8").strip().split("\n")
        return [float(line.strip()) for line in lines if line.strip()]
    except Exception as e:
        print(f"❌ Error reading baseline file: {path} ({e})")
        return []


def extract_benchmark_name(log_filename: str, parent_dir: Path = None):
    """Extract benchmark name from log filename or parent directory
    Example: benchmark_device_merge_sort_1.log -> device_merge_sort
    Example: patch_1_test.txt (in 20251230_block_run_length_decode/) -> block_run_length_decode
    """
    # Handle patch_*_test.txt files - extract from parent directory name
    if log_filename.startswith("patch_") and log_filename.endswith("_test.txt"):
        if parent_dir:
            # Extract from directory name like "20251230_block_run_length_decode"
            dir_name = parent_dir.name
            # Try to find benchmark name pattern (e.g., block_run_length_decode, device_merge_sort)
            # Look for common patterns: block_*, device_*, warp_*
            # Match from the pattern to the end of the string
            match = re.search(r"(block_|device_|warp_)[a-z_]+(?:_[a-z_]+)*", dir_name)
            if match:
                return match.group(0)
        # Fallback: try to extract from filename (shouldn't happen normally)
        return None
    
    # Handle benchmark_*_N.log files
    # Remove .log extension
    name = log_filename.replace(".log", "")
    # Remove benchmark_ prefix
    if name.startswith("benchmark_"):
        name = name[len("benchmark_"):]
    # Remove _N suffix (where N is a number)
    name = re.sub(r"_\d+$", "", name)
    return name


def compare_with_baseline(log_file: Path, baseline_file: Path):
    """Compare log file with baseline, return avg speedup or None if error"""
    log_values = parse_log(log_file)
    baseline_values = parse_baseline(baseline_file)

    if not log_values:
        print(f"  ❌ No valid data in log: {log_file.name}")
        return None

    if not baseline_values:
        print(f"  ❌ No valid data in baseline: {baseline_file.name}")
        return None

    if len(log_values) != len(baseline_values):
        print(f"  ❌ Mismatch: log has {len(log_values)} tests, baseline has {len(baseline_values)} tests")
        return None

    speedups = []
    for i, (opt_val, base_val) in enumerate(zip(log_values, baseline_values)):
        if base_val > 0:
            speedup = opt_val / base_val
            speedups.append(speedup)
        else:
            print(f"  ⚠ Warning: baseline value at index {i} is 0, skipping")

    if not speedups:
        print(f"  ❌ No valid speedups calculated")
        return None

    return sum(speedups) / len(speedups)


if __name__ == "__main__":
    # 读取输入
    if len(sys.argv) > 1:
        workspace_dir = Path(sys.argv[1])
    else:
        workspace_dir = Path("/mnt/raid0/yueliu14/AIG-Eval/workspace_MI308_cursor")
    print(f"Using workspace directory: {workspace_dir}")
    baseline_dir = Path("/mnt/raid0/yueliu14/mini-sweagent/case_study/rocprim/baseline_bandwidth")
    output_csv = Path("speedup_results.csv")

    if not workspace_dir.exists():
        print(f"❌ Workspace directory not found: {workspace_dir}")
        sys.exit(1)

    if not baseline_dir.exists():
        print(f"❌ Baseline directory not found: {baseline_dir}")
        sys.exit(1)

    # Find all subdirectories in workspace
    # subdirs = [d for d in workspace_dir.iterdir() if d.is_dir()]
    subdirs = [workspace_dir]
    if not subdirs:
        print(f"❌ No subdirectories found in {workspace_dir}")
        sys.exit(1)

    print(f"✅ Found {len(subdirs)} subdirectories to scan\n")

    # Find all log files from all subdirectories
    # Support both benchmark_*_N.log and patch_*_test.txt formats
    log_files = []
    for subdir in subdirs:
        # Try benchmark_*_N.log files
        for log_file in sorted(subdir.glob("benchmark_*_[0-9]*.log")):
            if log_file.stat().st_size == 0:
                print(f"⚠ Skipping empty file: {log_file}")
                continue
            log_files.append(log_file)
        
        # Also try patch_*_test.txt files
        for log_file in sorted(subdir.glob("patch_*_test.txt")):
            if log_file.stat().st_size == 0:
                print(f"⚠ Skipping empty file: {log_file}")
                continue
            log_files.append(log_file)

    if not log_files:
        print("❌ No valid log files found (looking for benchmark_*_N.log or patch_*_test.txt)")
        sys.exit(1)

    print(f"✅ Found {len(log_files)} log file(s) to compare\n")

    # Group results by benchmark name
    benchmark_results = {}  # {benchmark_name: [(log_file, speedup), ...]}

    for log_file in log_files:
        print(f"📊 Processing: {log_file.relative_to(workspace_dir)}")
        
        # Extract benchmark name
        parent_dir_for_extraction = log_file.parent if log_file.name.startswith("patch_") else None
        bench_name = extract_benchmark_name(log_file.name, parent_dir_for_extraction)
        
        if bench_name is None:
            print(f"  ❌ Could not extract benchmark name from: {log_file.name}\n")
            continue
        
        baseline_file = baseline_dir / f"{bench_name}.txt"

        if not baseline_file.exists():
            print(f"  ❌ Baseline file not found: {baseline_file.name}\n")
            continue

        print(f"  📌 Baseline: {baseline_file.name}")

        avg_speedup = compare_with_baseline(log_file, baseline_file)

        if avg_speedup is not None:
            print(f"  ✅ Average speedup = {avg_speedup:.3f}x\n")
            if bench_name not in benchmark_results:
                benchmark_results[bench_name] = []
            benchmark_results[bench_name].append((log_file, avg_speedup))
        else:
            print()

    # Find best speedup for each benchmark and write to CSV
    csv_data = []
    
    for bench_name, results in sorted(benchmark_results.items()):
        best_log, best_speedup = max(results, key=lambda x: x[1])
        csv_data.append({
            "benchmark": bench_name,
            "best_speedup": f"{best_speedup:.4f}",
            "log_file": str(best_log.relative_to(workspace_dir)),
            "num_attempts": len(results)
        })
    
    # Write to CSV
    if csv_data:
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["benchmark", "best_speedup", "log_file", "num_attempts"])
            writer.writeheader()
            writer.writerows(csv_data)
        
        print("=" * 60)
        print(f"✅ Results written to: {output_csv}")
        print("=" * 60)
        
        # Print summary
        print(f"\n📋 Summary ({len(csv_data)} benchmarks):")
        for row in sorted(csv_data, key=lambda x: float(x["best_speedup"]), reverse=True):
            print(f"  {row['best_speedup']}x  {row['benchmark']} ({row['num_attempts']} attempts)")
    else:
        print("⚠ No valid results to write")

