"""数据集级并行执行：把 ``--dataset a,b,c`` 拆成多个单数据集子进程。

benchmark 进程都是单线程的（实测 cpu/wall ≈ 1.0），数据集之间零依赖，
因此按数据集并行可以近似线性缩短墙钟。每个子进程独占一份临时索引目录，
不共享状态。

用法（在各 bench 脚本内部）：

    datasets = split_datasets(args.dataset)
    if len(datasets) > 1:
        return run_parallel(Path(__file__), raw_argv, datasets, args.jobs)
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

#: ``--output-json`` 中的占位符，会在每个子进程里替换为数据集名
DATASET_PLACEHOLDER = "{dataset}"

#: 不显式指定 ``--jobs`` 时的并行度上限（每个子进程峰值 RSS ~0.5 GB）
DEFAULT_MAX_JOBS = 4


def split_datasets(value: str) -> list[str]:
    """把 ``a,b,c`` 拆成数据集列表。"""
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_jobs(requested: int, datasets: Sequence[str]) -> int:
    """``--jobs 0``（默认）表示自动：min(数据集数, DEFAULT_MAX_JOBS)。"""
    if requested > 0:
        return min(requested, len(datasets))
    return min(len(datasets), DEFAULT_MAX_JOBS)


def child_argv(argv: Sequence[str], dataset: str) -> list[str]:
    """构造单个数据集的子进程参数。

    追加 ``--dataset <ds> --jobs 1`` 覆盖父进程的同名参数（argparse 取最后一个），
    因此调用方不需要从 argv 里剔除原值；``{dataset}`` 占位符在所有参数中替换。
    """
    resolved = [item.replace(DATASET_PLACEHOLDER, dataset) for item in argv]
    return [*resolved, "--dataset", dataset, "--jobs", "1"]


def run_parallel(
    script: Path, argv: Sequence[str], datasets: Sequence[str], jobs: int
) -> int:
    """并行执行各数据集并回放输出；任一数据集失败则返回非零。"""
    workers = resolve_jobs(jobs, datasets)

    def _run_one(dataset: str) -> tuple[str, int, str, str]:
        completed = subprocess.run(
            [sys.executable, str(script), *child_argv(argv, dataset)],
            capture_output=True,
            text=True,
            check=False,
        )
        return dataset, completed.returncode, completed.stdout, completed.stderr

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(_run_one, datasets))

    failed = 0
    for dataset, code, stdout, stderr in outcomes:
        print(f"===== dataset={dataset} exit={code}")
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
        if code != 0:
            failed += 1
    if failed:
        print(f"{failed}/{len(datasets)} dataset runs failed", file=sys.stderr)
    return 1 if failed else 0
