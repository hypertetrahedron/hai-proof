import io
import tarfile
from types import SimpleNamespace

import pytest

from hai_proof import images
from hai_proof.models import PLAIN, Requirement, TaskSpec, TreatmentSpec


def make_treatment(tmp_path, name="tx", requires=(), dockerfile=None, files=None) -> TreatmentSpec:
    d = tmp_path / name
    (d / "user").mkdir(parents=True, exist_ok=True)
    (d / "user" / "CLAUDE.md").write_text("hi")
    for k, v in (files or {}).items():
        (d / k).write_text(v)
    if dockerfile is not None:
        (d / "Dockerfile").write_text(dockerfile)
    return TreatmentSpec(name=name, path=d, requires=tuple(requires))


def make_task(tmp_path, tid="B1", install="pip install -e .") -> TaskSpec:
    d = tmp_path / "tasks" / tid
    (d / "repo").mkdir(parents=True)
    (d / "repo" / "a.py").write_text("x=1\n")
    (d / "hidden_tests").mkdir()
    (d / "hidden_tests" / "test_h.py").write_text("def test_h(): pass\n")
    return TaskSpec(id=tid, kind="bug", level=1, path=d, prompt="p", install=install)


class FakeEx:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.builds = []
        self.docker_calls = []

    def image_exists(self, tag):
        return tag in self.existing

    def build_image(self, tag, context_tar, *, dockerfile="Dockerfile", build_args=None, timeout=3600):
        self.builds.append((tag, context_tar, build_args))
        self.existing.add(tag)

    def docker(self, args, input=None, timeout=None, check=True):
        self.docker_calls.append(args)
        return SimpleNamespace(stdout=b"9.9.9\n", returncode=0)


def names(tar_bytes):
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        return [m.name for m in t.getmembers()]


def test_base_files_exist():
    assert (images.BASE_DIR / "base" / "Dockerfile").is_file()
    assert (images.BASE_DIR / "proxy" / "entrypoint.sh").is_file()


def test_tags_stable_and_shaped():
    assert images.base_tag("1.2.3") == images.base_tag("1.2.3")
    assert images.base_tag("1.2.3").startswith("hai-proof-base:1.2.3-")
    assert images.base_tag("1.2.3") != images.base_tag("1.2.4")
    assert images.proxy_tag().startswith("hai-proof-proxy:")


def test_plain_treatment_passthrough():
    assert images.treatment_tag("base:1", PLAIN) == "base:1"
    ex = FakeEx()
    assert images.build_treatment(ex, "base:1", PLAIN) == "base:1"
    assert ex.builds == []


def test_treatment_dockerfile_requirements(tmp_path):
    t = make_treatment(tmp_path, requires=[Requirement("bd", "npm i -g bd@1", "bd --version"),
                                           Requirement("os", "npm i -g os@2", "os --version")])
    lines = images.treatment_dockerfile("base:1", t).splitlines()
    assert lines[0] == "FROM base:1" and lines[1] == "USER root"
    i = lines.index("RUN npm i -g bd@1")
    assert lines[i + 1] == "RUN bd --version"
    assert "RUN npm i -g os@2" in lines and "RUN os --version" in lines
    assert lines[-2] == "USER agent"
    assert f"hai-proof.treatment_hash={t.content_hash()}" in lines[-1]
    assert "hai-proof.treatment=tx" in lines[-1]


def test_treatment_dockerfile_appended(tmp_path):
    t = make_treatment(tmp_path, dockerfile="RUN apt-get update\n")
    df = images.treatment_dockerfile("base:1", t)
    assert df.index("RUN apt-get update") < df.index("USER agent")


def test_treatment_dockerfile_rejects_from(tmp_path):
    t = make_treatment(tmp_path, dockerfile="FROM ubuntu\nRUN true\n")
    with pytest.raises(ValueError):
        images.treatment_dockerfile("base:1", t)
    t2 = make_treatment(tmp_path, name="ty", dockerfile="run true\n  from x\n")
    with pytest.raises(ValueError):
        images.treatment_dockerfile("base:1", t2)


def test_treatment_tag_changes_with_files(tmp_path):
    t = make_treatment(tmp_path, files={"extra.txt": "a"})
    tag1 = images.treatment_tag("base:1", t)
    (t.path / "extra.txt").write_text("b")
    tag2 = images.treatment_tag("base:1", t)
    assert tag1 != tag2 and tag1.startswith("hai-proof-treat-tx:")
    assert images.treatment_tag("base:2", t) != tag2


def test_trial_tag_and_dockerfile(tmp_path):
    task = make_task(tmp_path)
    t1 = images.trial_tag("img:1", task)
    assert t1 == images.trial_tag("img:1", task)
    assert t1 != images.trial_tag("img:2", task)
    (task.repo_dir / "a.py").write_text("x=2\n")
    assert images.trial_tag("img:1", task) != t1
    df = images.trial_dockerfile("img:1", task)
    assert "FROM img:1" in df and "COPY --chown=agent:agent repo/ /work/" in df
    assert "RUN pip install -e ." in df and "LABEL hai-proof.task=B1" in df
    assert "hidden" not in df


def test_trial_tag_ignores_hidden_tests(tmp_path):
    task = make_task(tmp_path)
    t1 = images.trial_tag("img:1", task)
    (task.hidden_tests_dir / "test_h.py").write_text("changed")
    assert images.trial_tag("img:1", task) == t1


def test_build_treatment_calls_executor(tmp_path):
    t = make_treatment(tmp_path, requires=[Requirement("a", "echo a", "true")])
    ex = FakeEx()
    tag = images.build_treatment(ex, "base:1", t)
    assert len(ex.builds) == 1 and ex.builds[0][0] == tag
    n = names(ex.builds[0][1])
    assert n[0] == "Dockerfile" and all(x.startswith("bundle/") for x in n[1:]) and "bundle/user/CLAUDE.md" in n
    images.build_treatment(ex, "base:1", t)
    assert len(ex.builds) == 1  # skipped, exists
    images.build_treatment(ex, "base:1", t, force=True)
    assert len(ex.builds) == 2


def test_build_base_and_proxy():
    ex = FakeEx()
    tag = images.build_base(ex, "1.2.3")
    assert tag == images.base_tag("1.2.3")
    assert ex.builds[0][2] == {"CLAUDE_CODE_VERSION": "1.2.3"}
    n = names(ex.builds[0][1])
    assert "Dockerfile" in n and "hai_proof_wrap.py" in n and "hai_proof_grade.py" in n
    images.build_base(ex, "1.2.3")
    assert len(ex.builds) == 1
    ptag = images.build_proxy(ex)
    assert ptag == images.proxy_tag() and "entrypoint.sh" in names(ex.builds[1][1])
    images.build_proxy(ex)
    assert len(ex.builds) == 2


def test_trial_context_has_repo_never_hidden(tmp_path):
    task = make_task(tmp_path)
    ex = FakeEx()
    tag = images.build_trial(ex, "img:1", task)
    n = names(ex.builds[0][1])
    assert ex.builds[0][0] == tag
    assert "Dockerfile" in n and "repo/a.py" in n
    assert not any("hidden" in x for x in n)
    images.build_trial(ex, "img:1", task)
    assert len(ex.builds) == 1


def test_resolve_cli_version():
    ex = FakeEx()
    assert images.resolve_cli_version(ex, "latest") == "9.9.9"
    assert ex.docker_calls[0][:3] == ["run", "--rm", "node:22-slim"]
    ex2 = FakeEx()
    assert images.resolve_cli_version(ex2, "1.0.5") == "1.0.5"
    assert ex2.docker_calls == []
