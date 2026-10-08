"""Image tags, Dockerfile generation and builds (DESIGN 3.4, 3.5). Pure functions plus thin executor calls."""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
from pathlib import Path
from typing import Any

from .models import TaskSpec, TreatmentSpec
from .tarutil import tar_directory, tar_files

BASE_DIR = Path(__file__).resolve().parents[2] / "image"  # repo-root/image

_SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache"}
_FROM_RE = re.compile(r"^\s*FROM\s", re.IGNORECASE | re.MULTILINE)


# --------------------------------------------------------------------------- hashing / tags


def _hash_dir(d: Path) -> str:
    h = hashlib.sha256()
    if d.is_dir():
        for f in sorted(p for p in d.rglob("*") if p.is_file()):
            rel = f.relative_to(d)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            h.update(rel.as_posix().encode())
            h.update(b"\0")
            # normalise line endings so Windows checkouts hash like Linux ones
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
    return h.hexdigest()


def _h(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\0")
    return h.hexdigest()


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9_.-]+", "-", s.lower()).strip("-.")
    return s or "x"


def base_tag(cli_version: str) -> str:
    return f"hai-proof-base:{slug(cli_version)}-{_hash_dir(BASE_DIR / 'base')[:8]}"


def proxy_tag() -> str:
    return f"hai-proof-proxy:{_hash_dir(BASE_DIR / 'proxy')[:8]}"


def treatment_tag(base: str, t: TreatmentSpec) -> str:
    if t.is_plain:
        return base
    return f"hai-proof-treat-{slug(t.name)}:{t.content_hash()}-{_h(base)[:6]}"


def trial_tag(arm_image: str, task: TaskSpec) -> str:
    return f"hai-proof-trial-{slug(task.id)}:{_h(arm_image, _hash_dir(task.repo_dir), task.install)[:12]}"


# --------------------------------------------------------------------------- Dockerfiles


def treatment_dockerfile(base: str, t: TreatmentSpec) -> str:
    lines = [f"FROM {base}", "USER root"]
    for r in t.requires:
        lines.append(f"# requirement: {r.name}")
        lines.append(f"RUN {r.install}")
        lines.append(f"RUN {r.check}")
    df = t.dockerfile
    if df is not None:
        extra = df.read_text(encoding="utf-8")
        if _FROM_RE.search(extra):
            raise ValueError(f"treatment {t.name!r}: Dockerfile must not contain FROM (it is appended to the base image)")
        lines.append("# --- treatment Dockerfile ---")
        lines.append(extra.rstrip("\n"))
    lines.append("USER agent")
    lines.append(f"LABEL hai-proof.treatment={t.name} hai-proof.treatment_hash={t.content_hash()}")
    return "\n".join(lines) + "\n"


def trial_dockerfile(arm_image: str, task: TaskSpec) -> str:
    # Hidden tests are NEVER copied into the image.
    return "\n".join([
        f"FROM {arm_image}",
        "COPY --chown=agent:agent repo/ /work/",
        "WORKDIR /work",
        f"RUN {task.install}",
        f"LABEL hai-proof.task={task.id}",
    ]) + "\n"


# --------------------------------------------------------------------------- builds


def _api(ex: Any) -> Any:
    """`ex` may be an executor object or the hai_proof.executor module; None falls back to the module."""
    if ex is not None and hasattr(ex, "build_image") and hasattr(ex, "image_exists"):
        return ex
    from . import executor  # late import: sibling module written separately

    return executor


def build_base(ex: Any, cli_version: str, *, force: bool = False) -> str:
    executor = _api(ex)

    tag = base_tag(cli_version)
    if force or not executor.image_exists(tag):
        ctx = tar_directory(BASE_DIR / "base")
        executor.build_image(tag, ctx, build_args={"CLAUDE_CODE_VERSION": cli_version})
    return tag


def build_proxy(ex: Any, *, force: bool = False) -> str:
    executor = _api(ex)

    tag = proxy_tag()
    if force or not executor.image_exists(tag):
        executor.build_image(tag, tar_directory(BASE_DIR / "proxy"))
    return tag


def build_treatment(ex: Any, base: str, t: TreatmentSpec, *, force: bool = False) -> str:
    executor = _api(ex)

    if t.is_plain:
        return base
    tag = treatment_tag(base, t)
    if force or not executor.image_exists(tag):
        # The bundle is in the context under bundle/ so a treatment Dockerfile can COPY its own files.
        executor.build_image(tag, _merge_tars(tar_files({"Dockerfile": treatment_dockerfile(base, t)}),
                                              tar_directory(t.path, "bundle")))
    return tag


def build_trial(ex: Any, arm_image: str, task: TaskSpec, *, force: bool = False) -> str:
    executor = _api(ex)

    tag = trial_tag(arm_image, task)
    if force or not executor.image_exists(tag):
        ctx = _trial_context(arm_image, task)
        executor.build_image(tag, ctx)
    return tag


def _trial_context(arm_image: str, task: TaskSpec) -> bytes:
    return _merge_tars(tar_files({"Dockerfile": trial_dockerfile(arm_image, task)}),
                       tar_directory(task.repo_dir, "repo"))


def _merge_tars(*blobs: bytes) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as dst:
        for blob in blobs:
            with tarfile.open(fileobj=io.BytesIO(blob)) as src:
                for m in src.getmembers():
                    dst.addfile(m, src.extractfile(m) if m.isfile() else None)
    return out.getvalue()


def resolve_cli_version(ex: Any, requested: str) -> str:
    executor = _api(ex)

    if requested != "latest":
        return requested
    cp = executor.docker(["run", "--rm", "node:22-slim", "npm", "view", "@anthropic-ai/claude-code", "version"],
                         timeout=300)
    ver = cp.stdout.decode().strip().splitlines()[-1].strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+\S*", ver):
        raise RuntimeError(f"could not resolve Claude Code version, got {ver!r}")
    return ver
